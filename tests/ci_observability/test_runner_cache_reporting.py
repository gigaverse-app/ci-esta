from datetime import timedelta

import pytest

from ci_esta.ci_observability.efficiency import collect_measurements
from ci_esta.ci_observability.github import GitHubActionsClient
from ci_esta.ci_observability.models import GitHubJobV1, GitHubRunV1, GitHubStepV1
from ci_esta.ci_observability.report import render_markdown
from ci_esta.measurements import CacheOperationMeasurement
from tests.ci_observability.builders import RECORDED_AT, artifact
from tests.ci_observability.efficiency_builders import report


def test_runner_labels_are_visible_without_decoding_a_billing_sku():
    measured = report(labels=["ubuntu-latest"], runner_name="GitHub Actions 123", runner_group_name="GitHub Actions")
    sticky = render_markdown(measured)
    assert "Runners: `ubuntu-latest`" in sticky.split("<details>")[0]
    assert "`GitHub Actions 123` / `GitHub Actions`" in sticky
    assert measured.latest_attempt_jobs[0].runner_name == "GitHub Actions 123"


def test_uninstrumented_non_python_workflow_does_not_request_pytest_setup():
    sticky = render_markdown(report(labels=["ubuntu-latest"]))
    assert "ci-esta-pytest run-local" not in sticky


def test_pytest_workflow_keeps_its_missing_instrumentation_advice():
    measured = report().model_copy(update={"extensions": {"pytest": {
        "shard_count": 2, "wall_seconds": 10, "total_test_seconds": 15}}})
    assert "ci-esta-pytest run-local" in render_markdown(measured)


def test_small_measured_cache_work_is_not_displayed_as_zero_or_unknown():
    cache = CacheOperationMeasurement(run_id=431, run_attempt=2, head_sha="a" * 40, job="Tests",
                                      scope="Bun", cache_kind="download", outcome="exact-hit",
                                      restore_seconds=0.35, sync_seconds=0.003, sync_outcome="success")
    sticky = render_markdown(report().model_copy(update={"measurements": [cache]}))
    assert "| exact-hit | &lt;1s | unavailable | success (&lt;1s) |" in sticky


@pytest.mark.parametrize("case", ["valid", "stale", "foreign", "missing", "skipped", "ambiguous"])
def test_cache_collector_uses_source_attempt_steps_and_keeps_unknown_durations(case):
    measurement = CacheOperationMeasurement(
        run_id=431, run_attempt=1 if case == "stale" else 2, head_sha="a" * 40,
        job="Tests", scope="TypeScript", cache_kind="build", outcome="fallback-hit",
        restore_step="Restore build", save_step="Save build", restore_seconds=999,
    )
    upload = artifact(1, 431, fork=case == "foreign").model_copy(update={"name": "ci-esta-cache-operation-tests-2"})

    class API(GitHubActionsClient):
        def __init__(self):
            pass

        def list_artifacts(self, name, run_id):
            return [upload]

        def read_single_file_artifact(self, artifact_id):
            return measurement.model_dump_json().encode()

    step = GitHubStepV1(number=1, name="Restore build", status="completed",
                       conclusion="skipped" if case == "skipped" else "success",
                       started_at=RECORDED_AT, completed_at=RECORDED_AT + timedelta(seconds=3))
    jobs = [GitHubJobV1(id=1, name="Tests", run_attempt=2, status="completed", conclusion="success",
                       steps=[] if case == "missing" else [step])]
    if case == "ambiguous":
        jobs.append(jobs[0].model_copy(update={"id": 2}))
    run = GitHubRunV1(id=431, run_attempt=2, head_sha="a" * 40, name="CI",
                     status="completed", created_at=RECORDED_AT)
    records, errors = collect_measurements(API(), run, jobs)
    if case in {"stale", "foreign"}:
        assert records == []
        assert bool(errors) is (case == "foreign")
        return
    assert errors == []
    assert len(records) == 1
    assert records[0].restore_seconds == (3 if case == "valid" else None)
    assert records[0].save_seconds is None
    sticky = render_markdown(report().model_copy(update={"measurements": records}))
    assert "| `Tests` | `TypeScript` | build | fallback-hit |" in sticky
    assert "1/1</strong> cache restores" in sticky


def test_bun_capacity_is_visible_above_collapsed_details():
    from ci_esta.ci_observability.work_selection import WorkSelectionV1

    plan = WorkSelectionV1(run_id=431, run_attempt=2, head_sha="a" * 40,
        provider="Bun", input_identity="a" * 40, decisions=[{
            "name": "Bun tests", "decision": "run", "reason": "Full checkpoint",
            "execution": {"mode": "full", "status": "passed", "total_files": 1,
                "executed_files": ["value.test.ts"], "tested_sha": "a" * 40,
                "runtime": "Bun 1.4.2", "cpu_count": 16, "worker_limit": 12, "runner_label": "16vcpu-runner"}}])
    sticky = render_markdown(report().model_copy(update={"work_selection": plan}))
    header = sticky.split("<details>")[0]
    assert "Bun tests: `16vcpu-runner` · 16 visible CPUs · 12 worker limit" in header
