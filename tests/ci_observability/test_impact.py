from datetime import timedelta

import pytest

from ci_esta.ci_observability.models import ActionsJobGateSelectorV1
from ci_esta.ci_observability.report import build_report, render_markdown
from tests.ci_observability.test_report import (
    FIRST_END,
    FIRST_START,
    OBSERVED_AT,
    REPOSITORY,
    RUN_ATTEMPT,
    _job,
    _run,
)


def test_plain_reports_keep_timeline_inside_closed_diagnostics():
    job = _job(job_id=1, name="checks", attempt=RUN_ATTEMPT,
               started_at=FIRST_START, completed_at=FIRST_END)
    report = build_report(repository=REPOSITORY, pull_request_number=None, run=_run(),
                          latest_jobs=[job], billing_jobs=[job], commit_statuses=[],
                          gate_selectors=[ActionsJobGateSelectorV1(kind="actions_job", job_name="checks")],
                          observed_at=OBSERVED_AT, job_dependencies={"checks": []})
    sticky = render_markdown(report)
    timeline = sticky.index("```mermaid")
    assert sticky.rfind("<details>", 0, timeline) > sticky.rfind("</details>", 0, timeline)
    assert "Timeline and critical path" in sticky[:timeline]


def test_comparison_collects_exact_attempts_and_rejects_non_comparable_successes():
    from ci_esta.ci_observability.impact import ImpactComparison, collect_impact

    before = _run().model_copy(update={"id": 1, "status": "completed", "conclusion": "success"})
    after = before.model_copy(update={"id": 2})
    jobs = {i: [_job(job_id=i, name="checks", attempt=RUN_ATTEMPT,
                    started_at=FIRST_START, completed_at=FIRST_START + timedelta(seconds=seconds))]
            for i, seconds in [(1, 100), (2, 25)]}

    class Client:
        def get_run(self, run_id, *, run_attempt):
            assert run_attempt == RUN_ATTEMPT
            return {1: before, 2: after}[run_id]

        def list_jobs(self, run_id, *, include_all_attempts, run_attempt):
            assert not include_all_attempts and run_attempt == RUN_ATTEMPT
            return jobs[run_id]

    request = ImpactComparison(label="Tests", metric="runner", context="Same revision; full versus selected",
        before=dict(run_id=1, run_attempt=RUN_ATTEMPT, head_sha=before.head_sha),
        after=dict(run_id=2, run_attempt=RUN_ATTEMPT, head_sha=after.head_sha))
    result = collect_impact(Client(), [request])[0]
    assert (result.before_seconds, result.after_seconds) == (100, 25)
    assert result.error is None
    jobs[2][0] = jobs[2][0].model_copy(update={"conclusion": "failure"})
    result = collect_impact(Client(), [request])[0]
    assert result.error and result.after_seconds is None


@pytest.mark.parametrize("change", ["head", "attempt", "missing_time"])
def test_invalid_measurements_never_become_zero_or_savings(change):
    from ci_esta.ci_observability.impact import ImpactComparison, collect_impact

    run = _run().model_copy(update={"id": 1, "status": "completed", "conclusion": "success"})
    job = _job(job_id=1, name="checks", attempt=RUN_ATTEMPT,
               started_at=FIRST_START, completed_at=FIRST_END)
    if change == "head":
        run = run.model_copy(update={"head_sha": "b" * 40})
    elif change == "attempt":
        job = job.model_copy(update={"run_attempt": 99})
    else:
        job = job.model_copy(update={"completed_at": None})

    class Client:
        def get_run(self, *args, **kwargs):
            return run

        def list_jobs(self, *args, **kwargs):
            return [job]

    request = ImpactComparison(label="Tests", metric="runner", context="Full versus selected",
        before=dict(run_id=1, run_attempt=RUN_ATTEMPT, head_sha="a" * 40),
        after=dict(run_id=2, run_attempt=RUN_ATTEMPT, head_sha="a" * 40))
    assert collect_impact(Client(), [request])[0].error
