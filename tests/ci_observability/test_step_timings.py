from datetime import datetime, timezone

import pytest

from ci_esta.ci_observability.models import CiObservabilityReportV1, GitHubJobV1, GitHubRunV1
from ci_esta.ci_observability.report import build_report, render_markdown


def report_with_steps(steps: list[dict[str, object]]) -> CiObservabilityReportV1:
    job = GitHubJobV1.model_validate(
        {
            "id": 10,
            "name": "tests | <job>",
            "status": "completed",
            "conclusion": "success",
            "started_at": "2026-10-22T10:00:00Z",
            "completed_at": "2026-10-22T10:02:00Z",
            "steps": steps,
        }
    )
    run = GitHubRunV1.model_validate(
        {
            "id": 20,
            "name": "CI",
            "run_attempt": 1,
            "status": "completed",
            "conclusion": "success",
            "created_at": "2026-10-22T10:00:00Z",
            "head_sha": "a" * 40,
        }
    )
    return build_report(
        repository="example/project",
        pull_request_number=None,
        run=run,
        latest_jobs=[job],
        billing_jobs=[job],
        commit_statuses=[],
        gate_selectors=[],
        observed_at=datetime(2026, 10, 22, 10, 3, tzinfo=timezone.utc),
    )


@pytest.mark.parametrize(
    "status,conclusion,start,end,seconds,timing",
    [
        ("completed", "success", "10:00:00", "10:01:00", 60, "complete"),
        ("completed", "failure", "10:00:00", "10:01:00", 60, "complete"),
        ("completed", "cancelled", "10:00:00", "10:01:00", 60, "complete"),
        ("completed", "success", "10:00:00", "10:00:00", 0, "complete"),
        ("completed", "skipped", "10:00:00", "10:01:00", None, "not_timed"),
        ("completed", "success", None, "10:01:00", None, "not_timed"),
        ("completed", "success", "10:00:00", None, None, "not_timed"),
        ("completed", "success", "10:01:00", "10:00:00", None, "not_timed"),
        ("in_progress", None, "10:00:00", None, 180, "accrued"),
        ("queued", None, None, None, None, "not_timed"),
    ],
)
def test_step_timing_preserves_api_evidence_without_double_counting(
    status: str,
    conclusion: str | None,
    start: str | None,
    end: str | None,
    seconds: float | None,
    timing: str,
) -> None:
    report = report_with_steps(
        [
            {
                "number": 1,
                "name": "Run tests",
                "status": status,
                "conclusion": conclusion,
                "started_at": f"2026-10-22T{start}Z" if start else None,
                "completed_at": f"2026-10-22T{end}Z" if end else None,
            }
        ]
    )
    restored = CiObservabilityReportV1.model_validate_json(report.model_dump_json())
    step = restored.latest_attempt_jobs[0].steps[0]
    assert (step.number, step.name, step.status, step.conclusion) == (1, "Run tests", status, conclusion)
    assert (step.wall_seconds, step.timing_status) == (seconds, timing)
    assert restored.billing_jobs[0].steps == restored.latest_attempt_jobs[0].steps
    assert restored.runner_cost.raw_runner_seconds == 120
    assert restored.runner_cost.estimated_rounded_runner_minutes == 2


def test_slowest_step_view_escapes_names_and_leaves_absent_timings_unknown() -> None:
    report = report_with_steps(
        [
            {
                "number": 1,
                "name": "Fast",
                "status": "completed",
                "conclusion": "success",
                "started_at": "2026-10-22T10:00:00Z",
                "completed_at": "2026-10-22T10:00:01Z",
            },
            {
                "number": 2,
                "name": "Install | <script>\npackages",
                "status": "completed",
                "conclusion": "success",
                "started_at": "2026-10-22T10:00:01Z",
                "completed_at": "2026-10-22T10:01:41Z",
            },
        ]
    )
    markdown = render_markdown(report)
    assert "Slowest step in each job" in markdown
    assert "`Install \\| <script> packages`" in markdown
    assert "100s" in markdown
    assert "https://github.com/example/project/actions/runs/20/job/10" in markdown
    unknown = render_markdown(report_with_steps([]))
    assert "| unavailable | unavailable |" in unknown


def test_old_report_without_steps_still_loads() -> None:
    data = report_with_steps([]).model_dump()
    for key in ("latest_attempt_jobs", "billing_jobs"):
        data[key][0].pop("steps", None)
    restored = CiObservabilityReportV1.model_validate(data)
    assert restored.latest_attempt_jobs[0].steps == []
