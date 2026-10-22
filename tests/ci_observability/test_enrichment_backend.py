"""Pin gigaverse-backend's enrichment profile, ported with its code.

These tests came with ``deployment/scripts/ci_observability_enrichment.py``
when it moved here (as of gigaverse-backend#4453's EKS-lane retirement); the
extension JSON, signal strings, and legacy metric names they assert are the
wire contract gigaverse-backend's dashboards and sticky already consume.
"""

import json
from pathlib import Path

import httpx
import pytest

from ci_esta.ci_observability.enrichment.backend import (
    artifacts,
    github,
    legacy,
    models,
)
from ci_esta.ci_observability.enrichment.primitives import write_pytest_metadata


def test_builds_typed_backend_enrichment_from_existing_artifacts(
    tmp_path: Path,
) -> None:
    write_pytest_metadata(
        tmp_path / "ci-pytest-timings.json",
        shard_count=3,
        wall_time="1m 34s",
        total_time="4m 21s",
    )
    (tmp_path / "coverage.xml").write_text('<coverage line-rate="0.642"/>')
    (tmp_path / "report-group-1.xml").write_text("""
        <testsuite tests="3" failures="1" errors="0" skipped="1" time="7.5">
          <testcase classname="tests.test_alpha" name="test_fast" time="0.5"/>
          <testcase classname="tests.test_alpha" name="test_slow" time="7.0">
            <failure/>
          </testcase>
        </testsuite>
        """)

    extension = artifacts.build_extension(
        tmp_path,
        models.GitHubEnrichment(),
    )

    assert extension.backend.model_dump(mode="json") == {
        "contract_version": "CI-OBS-BACKEND-ENRICH-v1",
        "pytest": {
            "shard_count": 3,
            "wall_seconds": 94.0,
            "total_test_seconds": 261.0,
            "passed": 1,
            "failed": 1,
            "errors": 0,
            "skipped": 1,
            "slowest": [
                {
                    "nodeid": "tests.test_alpha::test_slow",
                    "seconds": 7.0,
                },
                {
                    "nodeid": "tests.test_alpha::test_fast",
                    "seconds": 0.5,
                },
            ],
        },
        "coverage_percent": 64.2,
        "infra_signals": [],
        "unavailable": [],
    }
    signals = artifacts.build_repository_signals(extension)
    assert [signal.key for signal in signals] == [
        "pytest_result",
        "pytest_parallelism",
        "slowest_tests",
        "line_coverage",
    ]
    assert signals[1].value == "3 shards · 1m 34s wall · 4m 21s summed"
    json.dumps(extension.model_dump(mode="json"))


def test_artifact_parsers_reject_xml_entities_without_crashing(tmp_path: Path) -> None:
    malicious_xml = """\
        <!DOCTYPE data [
          <!ENTITY leaked SYSTEM "file:///etc/passwd">
        ]>
        <testsuite tests="1" failures="0" errors="0" skipped="0" time="0">
          <testcase name="test_entity">&leaked;</testcase>
        </testsuite>
    """
    coverage_path = tmp_path / "coverage.xml"
    junit_path = tmp_path / "junit.xml"
    coverage_path.write_text(malicious_xml)
    junit_path.write_text(malicious_xml)

    assert artifacts.parse_coverage_xml(coverage_path) is None
    assert artifacts.parse_junit_files([junit_path]) is None


def test_legacy_metrics_preserve_dashboard_until_be_751() -> None:
    report = legacy.SharedReport(
        latest_attempt_jobs=[
            legacy.SharedObservedJob(
                name="Build image for tests",
                wall_seconds=123,
                start_offset_seconds=0,
                end_offset_seconds=123,
            ),
            legacy.SharedObservedJob(
                name="Test unit behavior · runner shard (1)",
                wall_seconds=94,
                start_offset_seconds=2,
                end_offset_seconds=96,
            ),
        ],
        required_gates=[legacy.SharedObservedGate(conclusion="success")],
        merge_ready_from_creation_seconds=130,
        merge_ready_from_run_start_seconds=125,
        workflow_initial_queue_seconds=5,
        longest_latest_job_seconds=123,
        runner_cost=legacy.SharedRunnerCost(
            raw_runner_seconds=300,
            estimated_rounded_runner_minutes=7,
            rounding_waste_seconds=120,
        ),
    )
    extension = models.BackendExtensions(
        backend=models.BackendEnrichment(
            pytest=models.PytestSnapshot(
                shard_count=3,
                wall_seconds=94,
                total_test_seconds=250,
                passed=100,
                failed=0,
                errors=0,
                skipped=2,
            ),
            coverage_percent=64.2,
        )
    )

    metrics = legacy.render_legacy_metrics(report, extension)

    assert 'ci_required_gate_elapsed_seconds{test_conclusion="success"} 125.0' in metrics
    assert 'ci_critical_path_seconds{test_conclusion="success"} 123.0' in metrics
    assert 'ci_elapsed_span_seconds{test_conclusion="success"} 123.0' in metrics
    assert 'ci_pytest_passed{test_conclusion="success"} 100' in metrics
    assert 'ci_coverage_pct{test_conclusion="success"} 64.2' in metrics


def test_backend_log_enrichment_paginates_future_matrix_growth() -> None:
    pages: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        page = int(request.url.params["page"])
        pages.append(page)
        count = 100 if page == 1 else 1
        return httpx.Response(
            200,
            json={
                "jobs": [
                    {
                        "id": page * 1000 + index,
                        "name": f"job-{page}-{index}",
                        "status": "completed",
                        "conclusion": "success",
                    }
                    for index in range(count)
                ]
            },
        )

    client = github.GitHubClient(
        "gigaverse-app/gigaverse-backend",
        "token",
        "https://api.github.test",
        transport=httpx.MockTransport(handler),
    )
    try:
        jobs = client.list_jobs("123")
    finally:
        client.close()

    assert len(jobs) == 101
    assert pages == [1, 2]


def test_backend_enrichment_fetches_logs_only_for_terminal_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requested_paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested_paths.append(request.url.path)
        return httpx.Response(
            200,
            json={
                "jobs": [
                    {
                        "id": 123,
                        "name": "Test unit behavior · runner shard (1)",
                        "status": "completed",
                        "conclusion": "skipped",
                    },
                    {
                        "id": 124,
                        "name": "Build image for tests",
                        "status": "completed",
                        "conclusion": "success",
                    },
                ]
            },
        )

    client = github.GitHubClient(
        "gigaverse-app/gigaverse-backend",
        "token",
        "https://api.github.test",
        transport=httpx.MockTransport(handler),
    )
    monkeypatch.setenv("GITHUB_RUN_ID", "456")
    monkeypatch.setattr(github, "github_client", lambda: client)

    enrichment = github.collect_github_enrichment()

    assert enrichment.unavailable == []
    assert requested_paths == ["/repos/gigaverse-app/gigaverse-backend/actions/runs/456/jobs"]
