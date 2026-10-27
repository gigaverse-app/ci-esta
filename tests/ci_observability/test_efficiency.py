"""Measured execution, not selection counts, explains the avoided work and shard pool."""

from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from ci_esta.ci_observability.github import GitHubActionsClient
from ci_esta.ci_observability.models import GitHubJobV1, GitHubRunV1, GitHubStepV1
from ci_esta.ci_observability.report import render_markdown
from ci_esta.measurements import ShardInterval
from tests.ci_observability.efficiency_builders import pool, report


def test_observed_intervals_define_occupancy_and_all_the_detail_sections_survive():
    measured = report().model_copy(update={"measurements": [pool()]})
    sticky = render_markdown(measured)
    assert "Sharding &amp; runner efficiency" in sticky
    assert "75%</strong> slot occupancy" in sticky
    assert "16" in sticky
    assert "5s idle slot-time" in sticky
    assert "CPU utilization" in sticky
    assert "What else avoided work?" in sticky
    assert "Timeline and critical path" in sticky
    assert "Runner minutes and cost by runner and job" in sticky
    assert "<picture>" in sticky
    assert "gantt" in sticky


def test_junit_aggregate_cannot_claim_pool_occupancy():
    measured = report().model_copy(update={"extensions": {
        "pytest": {"shard_count": 4, "wall_seconds": 10, "total_test_seconds": 30}}})
    sticky = render_markdown(measured)
    assert "4 shards" in sticky
    assert "unavailable</strong> slot occupancy" in sticky
    assert "75%" not in sticky


@pytest.mark.parametrize("structured", [True, False])
def test_ai_timing_summary_has_one_owner_and_keeps_legacy_fallback(structured):
    from ci_esta.ci_observability.enrichment.ai import AiExtensions, build_repository_signals

    extension = AiExtensions.model_validate({"ai": {"workflow_class": "python_tests", "pytest": {
        "shard_count": 16, "wall_seconds": 150, "total_test_seconds": 2187}}})
    measured = report().model_copy(update={
        "extensions": extension.model_dump(mode="json") if structured else {},
        "repository_signals": build_repository_signals(extension),
    })

    sticky = render_markdown(measured)

    assert sticky.count("36m 27s summed test time") == 1
    assert "2m 30s" in sticky
    assert ("Reported pytest timings: 16 shards" in sticky) is structured
    assert ("pytest: 16 shards · 2m 30s wall" in sticky) is not structured
    # Rendering keeps both raw representations available to JSON consumers.
    assert len(measured.repository_signals) == 1


@pytest.mark.parametrize("field,value", [("run_id", 432), ("run_attempt", 1), ("head_sha", "b" * 40)])
def test_report_rejects_measurements_from_another_source(field, value):
    measured = pool().model_copy(update={field: value})
    with pytest.raises(ValidationError, match="measurement.*provenance"):
        type(report()).model_validate({**report().model_dump(), "measurements": [measured]})


@pytest.mark.parametrize("end", [-1, float("nan"), float("inf")])
def test_invalid_intervals_cannot_create_efficiency(end):
    with pytest.raises(ValidationError):
        ShardInterval(index=1, start_seconds=0, end_seconds=end, exit_code=0)


def test_a_step_name_does_not_substitute_for_a_cache_measurement():
    from ci_esta.ci_observability.models import ObservedStepV1

    original = report()
    step = ObservedStepV1(number=1, name="CI-esta cache v1: hit", status="completed",
                          conclusion="success", timing_status="not_timed", wall_seconds=None)
    job = original.latest_attempt_jobs[0].model_copy(update={"steps": [step]})
    sticky = render_markdown(original.model_copy(update={"latest_attempt_jobs": [job]}))
    assert "not recorded</strong> environment caches" in sticky
    assert "Cache time saved is unavailable" in sticky


@pytest.mark.parametrize("variant", [
    "valid", "executed", "stale", "foreign", "bad-source", "missing-time", "partial",
    "aggregate", "aggregate-fresh", "aggregate-wrong-receipt", "aggregate-failed", "aggregate-no-source-receipt",
])
def test_collector_binds_reuse_to_this_attempt_and_reads_actual_source_duration(variant):
    from ci_esta.ci_observability.efficiency import collect_measurements
    from ci_esta.measurements import ReusedLane, ReuseMeasurement
    from tests.ci_observability.builders import artifact

    now = datetime(2026, 10, 23, tzinfo=timezone.utc)
    current = GitHubRunV1(id=431, run_attempt=2, head_sha="a" * 40, name="CI", workflow_id=4,
                         status="completed", created_at=now)
    proof = GitHubJobV1(id=101, name="Tests", status="completed", conclusion="success",
                       started_at=None if variant == "missing-time" else now,
                       completed_at=now + timedelta(seconds=73))
    reused = ReuseMeasurement(run_id=431, run_attempt=1 if variant == "stale" else 2, head_sha="a" * 40,
                             receipt="Validated inputs example", lanes=[ReusedLane(
                                 lane="tests", job="Tests", source_run_id=420, source_attempt=1,
                                 source_head_sha="b" * 40, source_job_id=101, source_seconds=9999)])
    if variant == "partial":
        reused.lanes.append(reused.lanes[0].model_copy(update={"source_job_id": 999}))
    if variant.startswith("aggregate") and variant != "aggregate-no-source-receipt":
        proof = proof.model_copy(update={"steps": [GitHubStepV1(
            number=1, name=reused.receipt, status="completed", conclusion="success",
        )]})
    upload = artifact(123, 431, fork=variant == "foreign").model_copy(update={"name": "ci-esta-reuse-plan-2"})

    class API(GitHubActionsClient):
        def __init__(self):
            pass  # Remote boundaries below are in-memory; retain the production batch reader.

        def list_artifacts(self, name, run_id):
            assert name is None and run_id == 431
            return [upload]

        def read_single_file_artifact(self, artifact_id):
            assert artifact_id == 123
            return reused.model_dump_json().encode()

        def get_run(self, run_id, run_attempt):
            assert (run_id, run_attempt) == (420, 1)
            return current.model_copy(update={"id": 420, "run_attempt": 1,
                                              "head_sha": ("c" if variant == "bad-source" else "b") * 40})

        def list_jobs(self, run_id, include_all_attempts, run_attempt):
            assert (run_id, run_attempt, include_all_attempts) == (420, 1, False)
            return [proof]

    current_job = proof.model_copy(update={"id": 102, "run_attempt": 2,
                                          "conclusion": "success" if variant == "executed" else "skipped"})
    if variant.startswith("aggregate"):
        current_job = current_job.model_copy(update={
            "conclusion": "failure" if variant == "aggregate-failed" else "success",
            "steps": [GitHubStepV1(
                number=1, name="Validated inputs other" if variant == "aggregate-wrong-receipt" else reused.receipt,
                status="completed", conclusion="success" if variant == "aggregate-fresh" else "skipped",
            )],
        })
    records, errors = collect_measurements(API(), current, [current_job])
    lanes = [lane for record in records for lane in record.lanes]
    if variant in {"valid", "missing-time", "partial", "aggregate"}:
        assert len(lanes) == 1
        # A validating aggregate gate still executes. Its own duration is not
        # the duration of the child tests it avoided, which remains unknown.
        assert lanes[0].source_seconds == (None if variant in {"missing-time", "aggregate"} else 73)
        assert bool(errors) is (variant == "partial")
    else:
        assert lanes == []
        assert bool(errors) is (variant in {"foreign", "bad-source", "aggregate-no-source-receipt"})


def test_overlapping_pool_indices_withhold_global_occupancy():
    second = pool().model_copy(update={"pool": "second"})
    sticky = render_markdown(report().model_copy(update={"measurements": [pool(), second]}))
    assert "Overall occupancy unavailable (incomplete or overlapping pools)" in sticky
    assert "75%</strong> slot occupancy" not in sticky
