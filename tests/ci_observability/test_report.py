import re
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from pydantic import ValidationError
from pytest_selective.impact_models import SelectionExplanation

from ci_esta.ci_observability.models import (
    PYTEST_TIMING_SIGNAL,
    ActionsJobGateSelectorV1,
    CiObservabilityReportV1,
    CollectionStatus,
    CommitStatusGateSelectorV1,
    DirectPrerequisiteV1,
    GateKind,
    GitHubCommitStatusV1,
    GitHubJobV1,
    GitHubRunJobsV1,
    GitHubRunV1,
    RepositorySignalV1,
    RunnerCostV1,
    RunnerSkuRateV1,
    SelectionSectionV1,
)
from ci_esta.ci_observability.report import (
    STICKY_MARKER,
    build_report,
    build_unavailable_report,
    render_markdown,
    render_prometheus,
    sticky_snapshot,
)
from tests.ci_observability.builders import floor

REPOSITORY = "gigaverse-app/example"
RUN_ID = 12345
RUN_ATTEMPT = 2
PR_NUMBER = 86
HEAD_SHA = "a" * 40
WORKFLOW_NAME = "Primary CI"
CREATED_AT = datetime(2026, 7, 23, 6, 0, 0, tzinfo=timezone.utc)
RUN_STARTED_AT = datetime(2026, 7, 23, 6, 0, 5, tzinfo=timezone.utc)
OBSERVED_AT = datetime(2026, 7, 23, 6, 3, 0, tzinfo=timezone.utc)
FIRST_START = datetime(2026, 7, 23, 6, 0, 10, tzinfo=timezone.utc)
FIRST_END = datetime(2026, 7, 23, 6, 2, 11, tzinfo=timezone.utc)
SECOND_END = datetime(2026, 7, 23, 6, 1, 9, tzinfo=timezone.utc)
STATUS_END = datetime(2026, 7, 23, 6, 2, 20, tzinfo=timezone.utc)
GATE_RUNNER = "GitHub Actions 7"
STATUS_CONTEXT = "backend-trigger"
FIRST_JOB_ID = 101
SECOND_JOB_ID = 102
OLD_JOB_ID = 99
CANCELLED_JOB_ID = 103
PRIOR_RUN_ID = RUN_ID - 1
PRIOR_CREATED_AT = datetime(2026, 7, 23, 5, 59, 30, tzinfo=timezone.utc)
PRIOR_UPDATED_AT = datetime(2026, 7, 23, 6, 0, 30, tzinfo=timezone.utc)


def _run() -> GitHubRunV1:
    return GitHubRunV1(
        id=RUN_ID,
        name=WORKFLOW_NAME,
        run_attempt=RUN_ATTEMPT,
        status="in_progress",
        created_at=CREATED_AT,
        run_started_at=RUN_STARTED_AT,
        head_sha=HEAD_SHA,
    )


def _job(
    *,
    job_id: int,
    name: str,
    attempt: int,
    started_at: datetime | None,
    completed_at: datetime | None,
    status: str = "completed",
    conclusion: str | None = "success",
    runner_name: str | None = None,
    labels: list[str] | None = None,
) -> GitHubJobV1:
    return GitHubJobV1(
        id=job_id,
        name=name,
        run_attempt=attempt,
        status=status,
        conclusion=conclusion,
        started_at=started_at,
        completed_at=completed_at,
        runner_name=runner_name,
        labels=labels or [],
    )


@pytest.mark.parametrize("attempt", [1, 2])
def test_rerun_excludes_wait_before_attempt_from_critical_path_and_timeline(attempt: int) -> None:
    run = _run().model_copy(update={"run_attempt": attempt, "created_at": CREATED_AT - timedelta(hours=2)})
    jobs = [_job(job_id=FIRST_JOB_ID, name="Validation gate", attempt=attempt,
                 started_at=FIRST_START, completed_at=FIRST_END)]
    selector = ActionsJobGateSelectorV1(kind="actions_job", job_name="Validation gate")
    report = build_report(repository=REPOSITORY, pull_request_number=None, run=run, latest_jobs=jobs,
                          billing_jobs=jobs, commit_statuses=[], gate_selectors=[selector], observed_at=OBSERVED_AT,
                          job_dependencies={"Validation gate": []})
    expected = 7331 if attempt == 1 else 126
    assert report.critical_path is not None
    assert report.critical_path.elapsed_seconds == expected
    assert report.attempt_elapsed_seconds == expected
    assert report.latest_attempt_jobs[0].start_offset_seconds == (7210 if attempt == 1 else 5)
    assert report.workflow_job_admission_delay_seconds == (7210 if attempt == 1 else 5)
    assert report.merge_ready_from_creation_seconds == 7331  # Literal historical metric stays available.
    if attempt == 2:
        assert report.workflow_initial_queue_seconds is None  # Rerun-request time is not available.
        assert "2m 6s to CI gates passed" in render_markdown(report)
        assert "122m" not in render_markdown(report)


def test_commit_status_remains_reported_without_becoming_a_fictitious_dag_job() -> None:
    jobs = [_job(job_id=FIRST_JOB_ID, name="Validation gate", attempt=RUN_ATTEMPT,
                 started_at=FIRST_START, completed_at=FIRST_END)]
    selectors = [ActionsJobGateSelectorV1(kind="actions_job", job_name="Validation gate"),
                 CommitStatusGateSelectorV1(kind="commit_status", context="external/status")]
    report = build_report(repository=REPOSITORY, pull_request_number=None, run=_run(), latest_jobs=jobs,
                          billing_jobs=jobs, commit_statuses=[], gate_selectors=selectors, observed_at=OBSERVED_AT,
                          job_dependencies={"Validation gate": []})
    assert len(report.required_gates) == 2
    assert report.critical_path.status == "complete"
    assert report.critical_path.execution_path == ["Validation gate"]


def test_rerun_missing_attempt_start_does_not_substitute_original_creation_time() -> None:
    run = _run().model_copy(update={"run_started_at": None})
    jobs = [_job(job_id=FIRST_JOB_ID, name="Validation gate", attempt=2,
                 started_at=FIRST_START, completed_at=FIRST_END)]
    selector = ActionsJobGateSelectorV1(kind="actions_job", job_name="Validation gate")
    report = build_report(repository=REPOSITORY, pull_request_number=None, run=run, latest_jobs=jobs,
                          billing_jobs=jobs, commit_statuses=[], gate_selectors=[selector], observed_at=OBSERVED_AT,
                          job_dependencies={"Validation gate": []})
    assert report.critical_path is not None and report.critical_path.status == "unavailable"
    assert report.attempt_elapsed_seconds is None
    assert report.latest_attempt_jobs[0].start_offset_seconds is None


@pytest.mark.parametrize("duplicate", [False, True])
def test_job_name_gate_is_independent_of_runner_machine_and_rejects_ambiguity(duplicate: bool) -> None:
    jobs = [_job(job_id=FIRST_JOB_ID, name="Validation gate", attempt=RUN_ATTEMPT,
                 started_at=FIRST_START, completed_at=FIRST_END, runner_name="Hosted Agent")]
    if duplicate:
        jobs.append(jobs[0].model_copy(update={"id": SECOND_JOB_ID, "conclusion": "failure"}))
    selector = ActionsJobGateSelectorV1.model_validate({"kind": "actions_job", "job_name": "Validation gate"})
    report = build_report(repository=REPOSITORY, pull_request_number=None, run=_run(), latest_jobs=jobs,
                          billing_jobs=jobs, commit_statuses=[], gate_selectors=[selector], observed_at=OBSERVED_AT)
    assert report.required_gates[0].matched is (not duplicate)
    assert (report.merge_ready_from_creation_seconds is not None) is (not duplicate)
    assert report.collection_status == (CollectionStatus.PARTIAL if duplicate else CollectionStatus.COMPLETE)


@pytest.mark.parametrize("fields", [{}, {"job_name": "a", "runner_name": "b"}, {"job_name": ""}])
def test_gate_selector_requires_one_unambiguous_identity(fields: dict[str, str]) -> None:
    with pytest.raises(ValidationError):
        ActionsJobGateSelectorV1.model_validate({"kind": "actions_job", **fields})


def test_runner_cost_is_grouped_and_priced_by_configured_sku() -> None:
    """INVARIANT: heterogeneous runner minutes are priced by their own SKU."""
    standard_label = "ubuntu-24.04"
    larger_label = "8vcpu-runner"
    jobs = [
        _job(
            job_id=FIRST_JOB_ID,
            name="Standard setup",
            attempt=RUN_ATTEMPT,
            started_at=CREATED_AT,
            completed_at=datetime(2026, 7, 23, 6, 1, 1, tzinfo=timezone.utc),
            labels=[standard_label],
        ),
        _job(
            job_id=SECOND_JOB_ID,
            name="Larger pytest",
            attempt=RUN_ATTEMPT,
            started_at=CREATED_AT,
            completed_at=datetime(2026, 7, 23, 6, 2, 1, tzinfo=timezone.utc),
            labels=[larger_label],
        ),
    ]
    rates = [
        RunnerSkuRateV1(
            sku="actions_linux",
            runner_label=standard_label,
            usd_per_minute=Decimal("0.006"),
        ),
        RunnerSkuRateV1(
            sku="linux_8_core",
            runner_label=larger_label,
            usd_per_minute=Decimal("0.022"),
        ),
    ]

    report = build_report(
        repository=REPOSITORY,
        pull_request_number=PR_NUMBER,
        run=_run(),
        latest_jobs=jobs,
        billing_jobs=jobs,
        commit_statuses=[],
        gate_selectors=[
            ActionsJobGateSelectorV1(
                kind=GateKind.ACTIONS_JOB,
                runner_name="missing-gate-is-irrelevant-to-cost",
            )
        ],
        observed_at=OBSERVED_AT,
        runner_sku_rates=rates,
    )

    assert report.runner_cost.estimated_rounded_runner_minutes == 5
    assert report.runner_cost.estimated_cost_usd == Decimal("0.078")
    assert [(item.sku, item.estimated_rounded_runner_minutes) for item in report.runner_cost.by_sku] == [
        ("actions_linux", 2),
        ("linux_8_core", 3),
    ]
    assert report.runner_cost.unpriced_rounded_runner_minutes == 0
    markdown = render_markdown(report)
    assert "Estimated runner cost at configured rates: **$0.078**." in markdown
    assert any(line.endswith("| 5 min | $0.078 |") for line in markdown.splitlines())
    assert "| linux_8_core | 3 | $0.022 | $0.066 |" in markdown
    assert "ci_estimated_runner_cost_usd" in render_prometheus(report)


def test_runner_cost_withholds_total_when_a_timed_job_is_unpriced() -> None:
    """INVARIANT: a partial SKU table never presents a partial total as exact."""
    job = _job(
        job_id=FIRST_JOB_ID,
        name="Unknown runner",
        attempt=RUN_ATTEMPT,
        started_at=CREATED_AT,
        completed_at=datetime(2026, 7, 23, 6, 2, 1, tzinfo=timezone.utc),
        labels=["unconfigured-runner"],
    )
    report = build_report(
        repository=REPOSITORY,
        pull_request_number=PR_NUMBER,
        run=_run(),
        latest_jobs=[job],
        billing_jobs=[job],
        commit_statuses=[],
        gate_selectors=[],
        observed_at=OBSERVED_AT,
        runner_sku_rates=[
            RunnerSkuRateV1(
                sku="linux_8_core",
                runner_label="8vcpu-runner",
                usd_per_minute=Decimal("0.022"),
            )
        ],
    )

    assert report.runner_cost.estimated_cost_usd is None
    assert report.runner_cost.unpriced_rounded_runner_minutes == 3
    assert "Exact dollar cost withheld: 3 rounded runner min" in render_markdown(report)
    assert "ci_estimated_runner_cost_usd" not in render_prometheus(report)


def _gate_selectors() -> list[ActionsJobGateSelectorV1 | CommitStatusGateSelectorV1]:
    return [
        ActionsJobGateSelectorV1(
            kind=GateKind.ACTIONS_JOB,
            runner_name=GATE_RUNNER,
            direct_prerequisites=[
                DirectPrerequisiteV1(
                    job_id="plan",
                    display_name="Plan",
                    result="success",
                )
            ],
        ),
        CommitStatusGateSelectorV1(
            kind=GateKind.COMMIT_STATUS,
            context=STATUS_CONTEXT,
            display_name="Backend validation",
        ),
    ]


def test_report_separates_latest_topology_from_all_attempt_runner_cost() -> None:
    latest_jobs = [
        _job(
            job_id=FIRST_JOB_ID,
            name="Build: image",
            attempt=RUN_ATTEMPT,
            started_at=FIRST_START,
            completed_at=FIRST_END,
        ),
        _job(
            job_id=SECOND_JOB_ID,
            name="Required gate",
            attempt=RUN_ATTEMPT,
            started_at=FIRST_START,
            completed_at=SECOND_END,
            runner_name=GATE_RUNNER,
        ),
    ]
    old_attempt = _job(
        job_id=OLD_JOB_ID,
        name="Build: image",
        attempt=1,
        started_at=CREATED_AT,
        completed_at=datetime(2026, 7, 23, 6, 1, 1, tzinfo=timezone.utc),
        conclusion="failure",
    )
    statuses = [
        GitHubCommitStatusV1(
            context=STATUS_CONTEXT,
            state="success",
            created_at=CREATED_AT,
            updated_at=STATUS_END,
        )
    ]

    report = build_report(
        repository=REPOSITORY,
        pull_request_number=PR_NUMBER,
        run=_run(),
        latest_jobs=latest_jobs,
        billing_jobs=[old_attempt, *latest_jobs],
        commit_statuses=statuses,
        gate_selectors=_gate_selectors(),
        observed_at=OBSERVED_AT,
        repository_signals=[
            RepositorySignalV1(
                key="pytest",
                label="pytest",
                value="4271 passed, 0 failed",
            ),
            RepositorySignalV1(
                key="coverage",
                label="Coverage",
                value="70.5% line_rate",
            ),
        ],
    )

    assert report.collection_status == CollectionStatus.COMPLETE
    assert len(report.latest_attempt_jobs) == 2
    assert len(report.billing_jobs) == 3
    assert report.runner_cost.raw_runner_seconds == 241.0
    assert report.runner_cost.estimated_rounded_runner_minutes == 6
    assert report.runner_cost.rounding_waste_seconds == 119.0
    assert report.runner_cost.billed_attempts == [1, 2]
    assert report.runner_cost.unpriced_rounded_runner_minutes == 6
    assert report.merge_ready_from_creation_seconds == 140.0
    assert report.merge_ready_from_run_start_seconds == 135.0
    assert report.workflow_initial_queue_seconds is None
    assert report.workflow_job_admission_delay_seconds == 5.0
    assert report.merge_ready_after_job_admission_seconds == 130.0
    assert report.provenance.workflow_name == WORKFLOW_NAME
    assert report.longest_latest_job_name == "Build: image"
    assert report.longest_latest_job_seconds == 121.0

    markdown = render_markdown(report)
    assert markdown.startswith('<a href="https://github.com/gigaverse-app/ci-esta"><picture>')
    assert (
        "| Workflow | CI gates passed | First runner | Longest job | Runner time | Cost |\n"
        "|:--|--:|--:|:--|--:|--:|\n"
        f"| {WORKFLOW_NAME} | 2m 15s | after 5s | Build: image · 2m 1s | 6 min | — |\n"
    ) in markdown
    # One row per job, named in the left column; orange is the job that finished last before CI gates passed.
    assert "    section Build image\n    2m 1s :crit, j0, 2000-01-01 00:00:05, 2000-01-01 00:02:06\n" in markdown
    assert "    section Required gate\n    59s :done, j1, 2000-01-01 00:00:05, 2000-01-01 00:01:04\n" in markdown
    assert "    section ✅ CI gates passed 2m 15s\n    ✅ :active, m, 2000-01-01 00:02:15, 2000-01-01 00:02:56\n" in markdown
    assert "| Backend validation |" not in markdown
    assert "| Required gate | Plan | success |" in markdown
    assert "| Build: image | unavailable | unavailable | 1 | 61s | 2 | 1s | 59s |" in markdown
    assert "2.0 min (33%)" in markdown
    assert "_pytest: 4271 passed, 0 failed._" in markdown
    assert "_Coverage: 70.5% line\\_rate._" in markdown
    assert f"[run {RUN_ID}](https://github.com/{REPOSITORY}/actions/runs/{RUN_ID})" in markdown
    assert "transitive DAG" in markdown
    assert STICKY_MARKER in markdown
    assert sticky_snapshot(report).completed_gates == 2

    metrics = render_prometheus(report)
    assert 'gate_conclusion="success",schema_version="v1"' in metrics
    assert "ci_estimated_rounded_runner_minutes" in metrics
    assert "ci_workflow_job_admission_delay_seconds" in metrics
    assert "ci_merge_ready_after_job_admission_seconds" in metrics
    for forbidden_label in ("run_id=", "head_sha=", "attempt=", "job_name="):
        assert forbidden_label not in metrics


def test_report_separates_overlapping_prior_run_cost_from_current_run() -> None:
    runner_label = "8vcpu-runner"
    current_job = _job(
        job_id=FIRST_JOB_ID,
        name="Current tests",
        attempt=RUN_ATTEMPT,
        started_at=FIRST_START,
        completed_at=FIRST_END,
        runner_name=GATE_RUNNER,
        labels=[runner_label],
    )
    prior_run = GitHubRunV1(
        id=PRIOR_RUN_ID,
        name=WORKFLOW_NAME,
        run_attempt=1,
        status="completed",
        conclusion="cancelled",
        created_at=PRIOR_CREATED_AT,
        updated_at=PRIOR_UPDATED_AT,
        run_started_at=PRIOR_CREATED_AT,
        head_sha="b" * 40,
    )
    prior_jobs = [
        _job(
            job_id=OLD_JOB_ID,
            name="Superseded tests",
            attempt=1,
            started_at=PRIOR_CREATED_AT,
            completed_at=datetime(
                2026,
                7,
                23,
                6,
                0,
                31,
                tzinfo=timezone.utc,
            ),
            conclusion="cancelled",
            labels=[runner_label],
        ),
        _job(
            job_id=CANCELLED_JOB_ID,
            name="Superseded lint",
            attempt=1,
            started_at=CREATED_AT,
            completed_at=datetime(
                2026,
                7,
                23,
                6,
                0,
                20,
                tzinfo=timezone.utc,
            ),
            conclusion="cancelled",
            labels=[runner_label],
        ),
    ]
    report = build_report(
        repository=REPOSITORY,
        pull_request_number=PR_NUMBER,
        run=_run(),
        latest_jobs=[current_job],
        billing_jobs=[current_job],
        commit_statuses=[],
        gate_selectors=[
            ActionsJobGateSelectorV1(
                kind=GateKind.ACTIONS_JOB,
                runner_name=GATE_RUNNER,
            )
        ],
        observed_at=OBSERVED_AT,
        overlapping_prior_runs=[GitHubRunJobsV1(run=prior_run, jobs=prior_jobs)],
        runner_sku_rates=[
            RunnerSkuRateV1(
                sku="linux_8_core",
                runner_label=runner_label,
                usd_per_minute=Decimal("0.022"),
            )
        ],
    )

    assert report.runner_cost.estimated_rounded_runner_minutes == 3
    assert report.overlapping_prior_runner_cost.raw_runner_seconds == 81.0
    assert report.overlapping_prior_runner_cost.estimated_rounded_runner_minutes == 3
    assert report.overlapping_prior_runner_cost.estimated_cost_usd == Decimal("0.066")
    assert [item.run_id for item in report.overlapping_prior_runner_cost.runs] == [PRIOR_RUN_ID]

    markdown = render_markdown(report)
    assert "Estimated runner usage for this run: **3 rounded min**" in markdown
    assert "**1 prior same-PR/workflow run**" in markdown
    assert "consumed an estimated **3 rounded min**" in markdown
    assert "Combined observed estimate: **6 rounded min**" in markdown
    assert "Combined observed cost from configured rates: **$0.132**" in markdown
    assert f"[run {PRIOR_RUN_ID}]" in markdown
    assert "does not expose concurrency-group causality" in markdown

    metrics = render_prometheus(report)
    assert "ci_overlapping_prior_run_count" in metrics
    assert "ci_overlapping_prior_estimated_rounded_runner_minutes" in metrics


def test_active_skipped_reversed_and_missing_gate_data_are_explicit() -> None:
    active = _job(
        job_id=FIRST_JOB_ID,
        name="Active",
        attempt=RUN_ATTEMPT,
        started_at=FIRST_START,
        completed_at=None,
        status="in_progress",
        conclusion=None,
    )
    skipped = _job(
        job_id=SECOND_JOB_ID,
        name="Skipped",
        attempt=RUN_ATTEMPT,
        started_at=FIRST_END,
        completed_at=FIRST_START,
        conclusion="skipped",
    )
    reversed_job = _job(
        job_id=OLD_JOB_ID,
        name="Reversed",
        attempt=RUN_ATTEMPT,
        started_at=FIRST_END,
        completed_at=FIRST_START,
    )
    cancelled = _job(
        job_id=CANCELLED_JOB_ID,
        name="Cancelled",
        attempt=RUN_ATTEMPT,
        started_at=FIRST_START,
        completed_at=datetime(2026, 7, 23, 6, 0, 40, tzinfo=timezone.utc),
        conclusion="cancelled",
    )

    report = build_report(
        repository=REPOSITORY,
        pull_request_number=None,
        run=_run(),
        latest_jobs=[active, skipped, reversed_job, cancelled],
        billing_jobs=[active, skipped, reversed_job, cancelled],
        commit_statuses=[],
        gate_selectors=[],
        observed_at=OBSERVED_AT,
    )

    assert report.collection_status == CollectionStatus.PARTIAL
    assert report.collection_errors == ["required gate metadata was not provided"]
    assert report.runner_cost.raw_runner_seconds == 200.0
    assert report.runner_cost.estimated_rounded_runner_minutes == 4
    assert report.latest_attempt_jobs[0].timing_status == "accrued"
    assert report.latest_attempt_jobs[1].timing_status == "not_timed"
    assert report.latest_attempt_jobs[2].timing_status == "not_timed"
    assert report.latest_attempt_jobs[3].timing_status == "complete"
    assert report.merge_ready_from_creation_seconds is None
    markdown = render_markdown(report)
    assert "| gates running |" in markdown
    # Before CI gates passed there is no CI gates passed bar, and the chain is the longest one so far.
    assert "orange is the longest chain" in markdown
    assert "    section Active (running)\n    2m 50s :crit, j0, 2000-01-01 00:00:05, 2000-01-01 00:02:55\n" in markdown
    assert "section ✅ CI gates passed" not in markdown
    assert 'gate_conclusion="pending"' in render_prometheus(report)


@pytest.mark.parametrize("conclusion", ["success", "failure", "cancelled", "skipped", None])
def test_merge_ready_requires_success_and_ignores_later_reporting(conclusion: str | None) -> None:
    gate = _job(
        job_id=FIRST_JOB_ID,
        name="Required checks",
        attempt=RUN_ATTEMPT,
        started_at=FIRST_START,
        completed_at=FIRST_END,
        status="completed" if conclusion else "in_progress",
        conclusion=conclusion,
        runner_name=GATE_RUNNER,
    )
    reporting = _job(
        job_id=SECOND_JOB_ID,
        name="Publish artifacts",
        attempt=RUN_ATTEMPT,
        started_at=FIRST_END,
        completed_at=OBSERVED_AT,
    )
    report = build_report(
        repository=REPOSITORY,
        pull_request_number=PR_NUMBER,
        run=_run().model_copy(update={"updated_at": OBSERVED_AT}),
        latest_jobs=[gate, reporting],
        billing_jobs=[gate, reporting],
        commit_statuses=[],
        observed_at=OBSERVED_AT,
        gate_selectors=[ActionsJobGateSelectorV1(kind=GateKind.ACTIONS_JOB, runner_name=GATE_RUNNER)],
    )
    expected = (FIRST_END - CREATED_AT).total_seconds() if conclusion == "success" else None
    assert report.merge_ready_from_creation_seconds == expected
    markdown = render_markdown(report)
    if conclusion in {"failure", "cancelled", "skipped"}:
        assert "blocked" in markdown
        assert "gates running" not in markdown


def test_missing_selected_gate_marks_partial_without_hiding_cost() -> None:
    job = _job(
        job_id=FIRST_JOB_ID,
        name="Only job",
        attempt=RUN_ATTEMPT,
        started_at=FIRST_START,
        completed_at=SECOND_END,
    )
    selector = CommitStatusGateSelectorV1(
        kind=GateKind.COMMIT_STATUS,
        context=STATUS_CONTEXT,
    )

    report = build_report(
        repository=REPOSITORY,
        pull_request_number=PR_NUMBER,
        run=_run(),
        latest_jobs=[job],
        billing_jobs=[job],
        commit_statuses=[],
        gate_selectors=[selector],
        observed_at=OBSERVED_AT,
        collection_errors=["pagination was truncated"],
    )

    assert report.collection_status == CollectionStatus.PARTIAL
    assert report.collection_errors == [
        "pagination was truncated",
        f"required gates were not observed: {STATUS_CONTEXT}",
    ]
    assert report.runner_cost.estimated_rounded_runner_minutes == 1


def test_unavailable_report_is_schema_valid_and_fail_open() -> None:
    report = build_unavailable_report(
        repository=REPOSITORY,
        run_id=RUN_ID,
        run_attempt=RUN_ATTEMPT,
        head_sha=HEAD_SHA,
        pull_request_number=PR_NUMBER,
        observed_at=OBSERVED_AT,
        error="GitHub API unavailable",
    )

    assert report.collection_status == CollectionStatus.UNAVAILABLE
    assert report.provenance.workflow_created_at is None
    assert report.runner_cost.raw_runner_seconds == 0.0
    assert "Collection unavailable: GitHub API unavailable" in render_markdown(report)


def test_additive_admission_and_overlap_fields_accept_older_v1_artifacts() -> None:
    report = build_unavailable_report(
        repository=REPOSITORY,
        run_id=RUN_ID,
        run_attempt=RUN_ATTEMPT,
        head_sha=HEAD_SHA,
        pull_request_number=PR_NUMBER,
        observed_at=OBSERVED_AT,
        error="historical fixture",
    )
    historical_payload = report.model_dump()
    for field in (
        "workflow_job_admission_delay_seconds",
        "merge_ready_after_job_admission_seconds",
        "overlapping_prior_runner_cost",
    ):
        historical_payload.pop(field)

    validated = CiObservabilityReportV1.model_validate(historical_payload)

    assert validated.workflow_job_admission_delay_seconds is None
    assert validated.merge_ready_after_job_admission_seconds is None
    assert validated.overlapping_prior_runner_cost.runs == []
    assert validated.overlapping_prior_runner_cost.estimated_rounded_runner_minutes == 0


def test_complete_report_rejects_errors() -> None:
    report = build_unavailable_report(
        repository=REPOSITORY,
        run_id=RUN_ID,
        run_attempt=RUN_ATTEMPT,
        head_sha=HEAD_SHA,
        pull_request_number=PR_NUMBER,
        observed_at=OBSERVED_AT,
        error="expected",
    )

    with pytest.raises(ValidationError, match="complete reports cannot contain"):
        CiObservabilityReportV1.model_validate(
            {
                **report.model_dump(),
                "collection_status": CollectionStatus.COMPLETE,
            }
        )

    with pytest.raises(
        ValidationError,
        match="partial or unavailable reports require",
    ):
        CiObservabilityReportV1.model_validate(
            {
                **report.model_dump(),
                "collection_status": CollectionStatus.PARTIAL,
                "collection_errors": [],
            }
        )


def test_failed_gate_is_a_bounded_prometheus_conclusion() -> None:
    selector = CommitStatusGateSelectorV1(
        kind=GateKind.COMMIT_STATUS,
        context=STATUS_CONTEXT,
    )
    failed_status = GitHubCommitStatusV1(
        context=STATUS_CONTEXT,
        state="failure",
        created_at=CREATED_AT,
        updated_at=STATUS_END,
    )

    report = build_report(
        repository=REPOSITORY,
        pull_request_number=PR_NUMBER,
        run=_run(),
        latest_jobs=[],
        billing_jobs=[],
        commit_statuses=[failed_status],
        gate_selectors=[selector],
        observed_at=OBSERVED_AT,
    )

    assert 'gate_conclusion="failure"' in render_prometheus(report)


def test_gate_contract_rejects_arbitrary_dependency_outputs() -> None:
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        DirectPrerequisiteV1.model_validate(
            {
                "job_id": "unit",
                "result": "success",
                "secret_output": "must-not-cross-contract",
            }
        )

    with pytest.raises(ValidationError, match="String should match pattern"):
        RepositorySignalV1.model_validate(
            {
                "key": "Pytest Total",
                "label": "pytest",
                "value": "42 passed",
            }
        )

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        RepositorySignalV1.model_validate(
            {
                "key": "pytest",
                "label": "pytest",
                "value": "42 passed",
                "markdown": "<script>",
            }
        )

    report = build_unavailable_report(
        repository=REPOSITORY,
        run_id=RUN_ID,
        run_attempt=RUN_ATTEMPT,
        head_sha=HEAD_SHA,
        pull_request_number=PR_NUMBER,
        observed_at=OBSERVED_AT,
        error="fixture",
    )
    with pytest.raises(ValidationError, match="repository signal keys must be unique"):
        CiObservabilityReportV1.model_validate(
            {
                **report.model_dump(),
                "repository_signals": [
                    RepositorySignalV1(key="pytest", label="pytest", value="42 passed"),
                    RepositorySignalV1(key="pytest", label="pytest rerun", value="43 passed"),
                ],
            }
        )


MERGE_READY_SECONDS = 356
ROUNDED_MINUTES = 16
COST = Decimal("0.176")


def _sticky_with_selection(**report_changes: object) -> str:
    """A report carrying a test-selection section, rendered as the sticky."""
    report = build_report(
        repository=REPOSITORY,
        pull_request_number=PR_NUMBER,
        run=_run(),
        latest_jobs=[],
        billing_jobs=[],
        commit_statuses=[],
        gate_selectors=[],
        observed_at=OBSERVED_AT,
    )
    explanation = SelectionExplanation(base="base", head="head", graph_base="base", selected=1, total=2, floor=floor())
    changes = {"test_selection": SelectionSectionV1(explanation=explanation), **report_changes}
    return render_markdown(report.model_copy(update=changes))


def test_collapsed_sections_keep_titles_separate_from_visible_metrics_and_details() -> None:
    sticky = _sticky_with_selection(extensions={"pytest": {"shard_count": 4, "wall_seconds": 10}})
    summaries = re.findall(r"<summary>(.*?)</summary>", sticky, re.DOTALL)
    for title in ("Test selection", "What else avoided work?", "Sharding &amp; runner efficiency", "CI time and cost"):
        summary = next(value for value in summaries if f"<strong>{title}</strong>" in value)
        assert "<br>" in summary
        assert summary.count("<strong>") >= 2
    assert sticky.count("\n---\n") >= 5
    assert "<details open" not in sticky
    assert "Timeline and critical path" in sticky
    assert "Runner minutes and cost by runner and job" in sticky
    assert "Savings across selection, reuse, and caching are not additive." in sticky


@pytest.mark.parametrize("conclusion,expected", [
    ("success", "Required checks passed"),
    ("failure", "Required checks failed"),
    (None, "Required checks running"),
])
def test_status_line_reports_gate_results_independently_of_snapshot_completeness(conclusion, expected) -> None:
    gate = _job(job_id=FIRST_JOB_ID, name="Validation gate", attempt=RUN_ATTEMPT,
                started_at=FIRST_START, completed_at=FIRST_END if conclusion else None,
                status="completed" if conclusion else "in_progress", conclusion=conclusion)
    report = build_report(repository=REPOSITORY, pull_request_number=PR_NUMBER, run=_run(),
                          latest_jobs=[gate], billing_jobs=[gate], commit_statuses=[],
                          gate_selectors=[ActionsJobGateSelectorV1(kind="actions_job", job_name="Validation gate")],
                          observed_at=OBSERVED_AT)
    header = render_markdown(report).split("<details>", 1)[0]
    assert expected in header
    if conclusion != "success":
        assert "Required checks passed" not in header


def test_no_configured_gate_never_shows_a_passed_status() -> None:
    header = _sticky_with_selection().split("<details>", 1)[0]
    assert "Required checks unreported" in header
    assert "Required checks passed" not in header


@pytest.mark.parametrize("conclusion,expected", [
    ("success", "Required checks unavailable"),
    ("failure", "Required checks failed"),
])
def test_an_unobserved_gate_cannot_hide_a_failure_or_prove_success(conclusion, expected) -> None:
    job = _job(job_id=FIRST_JOB_ID, name="Tests", attempt=RUN_ATTEMPT,
               started_at=FIRST_START, completed_at=FIRST_END, conclusion=conclusion)
    report = build_report(repository=REPOSITORY, pull_request_number=PR_NUMBER, run=_run(),
                          latest_jobs=[job], billing_jobs=[job], commit_statuses=[],
                          gate_selectors=[ActionsJobGateSelectorV1(kind="actions_job", job_name=name)
                                          for name in ("Tests", "Missing gate")], observed_at=OBSERVED_AT)
    header = render_markdown(report).split("<details>", 1)[0]
    assert expected in header
    assert "Required checks passed" not in header


def test_visible_summary_text_cannot_inject_markup_or_expand_its_details() -> None:
    from ci_esta.ci_observability.markdown import report_section

    hostile = '</summary></details><details open><summary>injected'
    section = report_section(hostile, [hostile], ["Original diagnostics"], note=hostile)
    assert section.count("<details>") == section.count("</details>") == 1
    assert section.count("<summary>") == section.count("</summary>") == 1
    assert "<details open>" not in section
    assert section.count("&lt;details open&gt;") == 3
    assert "Original diagnostics" in section


@pytest.mark.parametrize(
    ("changes", "summary"),
    [
        (
            {
                "merge_ready_from_run_start_seconds": MERGE_READY_SECONDS,
                "runner_cost": RunnerCostV1(
                    raw_runner_seconds=0,
                    estimated_rounded_runner_minutes=ROUNDED_MINUTES,
                    rounding_waste_seconds=0,
                    billed_attempts=[RUN_ATTEMPT],
                    estimated_cost_usd=COST,
                ),
            },
            "<strong>16 min</strong> runner · <strong>$0.18</strong> est. cost",
        ),
        ({}, "<strong>0 min</strong> runner · <strong>unavailable</strong> est. cost"),
    ],
    ids=["complete-and-priced", "running-and-unpriced"],
)
def test_the_selection_sticky_keeps_cost_figures_visible_above_folded_details(
    changes: dict[str, object], summary: str,
) -> None:
    sticky = _sticky_with_selection(**changes)

    assert sticky.startswith('<a href="https://github.com/gigaverse-app/ci-esta"><picture>')
    assert "#### 🎯 Test selection" in sticky
    assert summary in sticky
    # The summary line stands in for the heading; the footer that identifies the sticky stays outside.
    assert "#### ⏱️ CI time and cost" not in sticky
    latency = sticky.index(summary)
    assert latency < sticky.index("| CI gates passed |") < sticky.index("</details>", latency) < sticky.index(STICKY_MARKER)


def test_a_report_without_a_selection_still_collapses_latency_and_cost() -> None:
    report = build_unavailable_report(
        repository=REPOSITORY,
        run_id=RUN_ID,
        run_attempt=RUN_ATTEMPT,
        head_sha=HEAD_SHA,
        pull_request_number=PR_NUMBER,
        observed_at=OBSERVED_AT,
        error="GitHub API unavailable",
    )

    assert "<details>\n<summary><strong>CI time and cost</strong>" in render_markdown(report)


def test_the_pytest_timing_signal_is_preserved_once_in_sharding_even_with_selection() -> None:
    timing = RepositorySignalV1(key=PYTEST_TIMING_SIGNAL, label="pytest", value="4 shards · 1m 18s wall")
    coverage = RepositorySignalV1(key="coverage", label="Coverage", value="81%")
    sticky = _sticky_with_selection(repository_signals=[timing, coverage])
    report = build_unavailable_report(
        repository=REPOSITORY,
        run_id=RUN_ID,
        run_attempt=RUN_ATTEMPT,
        head_sha=HEAD_SHA,
        pull_request_number=PR_NUMBER,
        observed_at=OBSERVED_AT,
        error="GitHub API unavailable",
        repository_signals=[timing, coverage],
    )

    assert "_Coverage: 81%._" in sticky
    assert sticky.count("pytest: 4 shards · 1m 18s wall.") == 1
    assert sticky.index("Sharding &amp; runner efficiency") < sticky.index("pytest: 4 shards") < sticky.index("CI time and cost")
    assert "pytest: 4 shards · 1m 18s wall." in render_markdown(report)


def test_the_sticky_marker_stays_out_of_the_visible_footer() -> None:
    footer = _sticky_with_selection().splitlines()[-2:]

    assert footer == [
        STICKY_MARKER,
        "<sub>[Reading this report](https://github.com/gigaverse-app/ci-esta/blob/main/docs/github-actions-observability.md) "
        f"· [run {RUN_ID}](https://github.com/{REPOSITORY}/actions/runs/{RUN_ID}) · schema `ci-observability/v1`</sub>",
    ]
