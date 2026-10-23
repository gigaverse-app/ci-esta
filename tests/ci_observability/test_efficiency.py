"""Measured execution, not selection counts, explains the avoided work and shard pool."""

from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from ci_esta.ci_observability.models import GitHubJobV1, GitHubRunV1
from ci_esta.ci_observability.report import build_report, render_markdown
from ci_esta.measurements import ShardInterval, ShardPoolMeasurement


def pool(**changes):
    return ShardPoolMeasurement.model_validate(dict(
        run_id=431, run_attempt=2, head_sha="a" * 40, pool="tests:1-2", configured_shards=2, cpu_count=16,
        shards=[dict(index=1, start_seconds=0, end_seconds=10, exit_code=0),
                dict(index=2, start_seconds=0, end_seconds=5, exit_code=0)], **changes))


def report():
    now = datetime(2026, 10, 23, tzinfo=timezone.utc)
    run = GitHubRunV1(id=431, run_attempt=2, head_sha="a" * 40, name="CI", status="completed",
                     created_at=now, run_started_at=now)
    job = GitHubJobV1(id=11, name="Tests", run_attempt=2, status="completed", conclusion="success",
                     started_at=now, completed_at=now + timedelta(seconds=60))
    return build_report(repository="org/repo", pull_request_number=1, run=run,
                        latest_jobs=[job], billing_jobs=[job], commit_statuses=[], gate_selectors=[],
                        observed_at=now + timedelta(seconds=60))


def test_observed_intervals_define_occupancy_and_all_the_detail_sections_survive():
    measured = report().model_copy(update={"measurements": [pool()]})
    sticky = render_markdown(measured)
    assert "Sharding &amp; runner efficiency" in sticky
    assert "75% slot occupancy" in sticky
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
    assert "occupancy unavailable" in sticky
    assert "75%" not in sticky


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
    assert "no measured cache lookups" in sticky
    assert "Cache time saved is unavailable" in sticky


@pytest.mark.parametrize("variant", ["valid", "executed", "stale", "foreign", "bad-source", "missing-time", "partial"])
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
    upload = artifact(123, 431, fork=variant == "foreign").model_copy(update={"name": "ci-esta-reuse-plan-2"})

    class API:
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
    records, errors = collect_measurements(API(), current, [current_job])
    lanes = [lane for record in records for lane in record.lanes]
    if variant in {"valid", "missing-time", "partial"}:
        assert len(lanes) == 1
        assert lanes[0].source_seconds == (None if variant == "missing-time" else 73)
        assert bool(errors) is (variant == "partial")
    else:
        assert lanes == []
        assert bool(errors) is (variant in {"foreign", "bad-source"})


def test_overlapping_pool_indices_withhold_global_occupancy():
    second = pool().model_copy(update={"pool": "second"})
    sticky = render_markdown(report().model_copy(update={"measurements": [pool(), second]}))
    assert "overall occupancy unavailable (incomplete or overlapping pools)" in sticky
    assert "75% slot occupancy" not in sticky
