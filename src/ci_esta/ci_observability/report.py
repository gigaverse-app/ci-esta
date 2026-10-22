"""
Pure CI observability accounting and rendering.
"""

from __future__ import annotations

import math
import re
from datetime import datetime
from decimal import Decimal

from pydantic import JsonValue

from ci_esta.ci_observability import brand, lanes, markdown, selection
from ci_esta.ci_observability.critical_path import analyze
from ci_esta.ci_observability.enrichment.primitives import format_seconds
from ci_esta.ci_observability.models import (
    PYTEST_TIMING_SIGNAL,
    ActionsJobGateSelectorV1,
    CiObservabilityReportV1,
    CollectionStatus,
    CommitStatusGateSelectorV1,
    GateKind,
    GateSelectorV1,
    GitHubCommitStatusV1,
    GitHubJobV1,
    GitHubRunJobsV1,
    GitHubRunV1,
    GitHubStepV1,
    LaneSelectionSectionV1,
    ObservedGateV1,
    ObservedJobV1,
    ObservedStepV1,
    OverlappingRunCostV1,
    OverlappingRunnerCostV1,
    RepositorySignalV1,
    RunnerCostV1,
    RunnerSkuCostV1,
    RunnerSkuRateV1,
    RunProvenanceV1,
    SelectionSectionV1,
    StickySnapshotV1,
    TimingStatus,
)

STICKY_MARKER = "<!-- ci-observability-v1 -->"
#: The keyed sticky marker's prefix. A bare marker is never a substring of a keyed one.
STICKY_KEY_MARKER_PREFIX = "<!-- ci-observability-v1 key="
SNAPSHOT_MARKER_PREFIX = "<!-- ci-observability-snapshot "


def _elapsed(start: datetime | None, end: datetime | None) -> float | None:
    if start is None or end is None:
        return None
    seconds = (end - start).total_seconds()
    return round(seconds, 1) if seconds > 0 else None


def _observe_step(step: GitHubStepV1, observed_at: datetime) -> ObservedStepV1:
    timing_status = TimingStatus.NOT_TIMED
    wall_seconds: float | None = None
    end = step.completed_at
    accrued = end is None and step.status == "in_progress"
    if accrued:
        end = observed_at
    if step.conclusion != "skipped" and step.started_at is not None and end is not None:
        seconds = (end - step.started_at).total_seconds()
        # GitHub timestamps have second precision: a real short step may measure 0s.
        if seconds >= 0:
            wall_seconds = round(seconds, 1)
            timing_status = TimingStatus.ACCRUED if accrued else TimingStatus.COMPLETE
    return ObservedStepV1(**step.model_dump(), timing_status=timing_status, wall_seconds=wall_seconds)


def _observe_job(job: GitHubJobV1, timeline_start: datetime, observed_at: datetime) -> ObservedJobV1:
    wall_seconds: float | None = None
    timing_status = TimingStatus.NOT_TIMED
    effective_end = job.completed_at

    if job.conclusion != "skipped":
        wall_seconds = _elapsed(job.started_at, job.completed_at)
        if wall_seconds is not None:
            timing_status = TimingStatus.COMPLETE
        elif job.status == "in_progress":
            wall_seconds = _elapsed(job.started_at, observed_at)
            effective_end = observed_at
            if wall_seconds is not None:
                timing_status = TimingStatus.ACCRUED

    rounded_minutes = math.ceil(wall_seconds / 60) if wall_seconds is not None else None
    lower_boundary = 60 * (rounded_minutes - 1) if rounded_minutes is not None else None
    upper_boundary = 60 * rounded_minutes if rounded_minutes is not None else None
    return ObservedJobV1(
        job_id=job.id,
        name=job.name,
        run_attempt=job.run_attempt,
        status=job.status,
        conclusion=job.conclusion,
        timing_status=timing_status,
        started_at=job.started_at,
        completed_at=job.completed_at,
        wall_seconds=wall_seconds,
        start_offset_seconds=_elapsed(timeline_start, job.started_at),
        end_offset_seconds=_elapsed(timeline_start, effective_end),
        rounded_minutes=rounded_minutes,
        rounding_waste_seconds=(
            round(upper_boundary - wall_seconds, 1) if upper_boundary is not None and wall_seconds is not None else None
        ),
        seconds_to_save_minute=(
            round(wall_seconds - lower_boundary, 1) if lower_boundary is not None and wall_seconds is not None else None
        ),
        seconds_until_next_minute=(
            round(upper_boundary - wall_seconds, 1) if upper_boundary is not None and wall_seconds is not None else None
        ),
        runner_labels=job.labels,
        steps=[_observe_step(step, observed_at) for step in job.steps],
    )


def _observe_actions_gate(
    selector: ActionsJobGateSelectorV1,
    latest_jobs: list[GitHubJobV1],
    run: GitHubRunV1,
) -> ObservedGateV1:
    matches = [item for item in latest_jobs if (
        item.name == selector.job_name if selector.job_name is not None else item.runner_name == selector.runner_name
    )]
    # Ambiguous names cannot prove a gate: never choose a passing duplicate over a failure.
    job = matches[0] if len(matches) == 1 else None
    identity = selector.job_name if selector.job_name is not None else selector.runner_name
    assert identity is not None  # Validated by ActionsJobGateSelectorV1.one_identity.
    completed_at = job.completed_at if job is not None else None
    return ObservedGateV1(
        kind=GateKind.ACTIONS_JOB,
        identity=identity,
        display_name=selector.display_name or (job.name if job is not None else identity),
        status=job.status if job is not None else "missing",
        conclusion=job.conclusion if job is not None else None,
        matched=job is not None,
        observed_job_id=job.id if job is not None else None,
        completed_at=completed_at,
        elapsed_from_creation_seconds=_elapsed(run.created_at, completed_at),
        elapsed_from_run_start_seconds=_elapsed(run.run_started_at, completed_at),
        direct_prerequisites=selector.direct_prerequisites,
    )


def _observe_status_gate(
    selector: CommitStatusGateSelectorV1,
    statuses: list[GitHubCommitStatusV1],
    run: GitHubRunV1,
) -> ObservedGateV1:
    status = next((item for item in statuses if item.context == selector.context), None)
    completed_at = status.updated_at if status is not None and status.state != "pending" else None
    return ObservedGateV1(
        kind=GateKind.COMMIT_STATUS,
        identity=selector.context,
        display_name=selector.display_name or selector.context,
        status=status.state if status is not None else "missing",
        conclusion=status.state if status is not None and status.state != "pending" else None,
        matched=status is not None,
        observed_job_id=None,
        completed_at=completed_at,
        elapsed_from_creation_seconds=_elapsed(run.created_at, completed_at),
        elapsed_from_run_start_seconds=_elapsed(run.run_started_at, completed_at),
        direct_prerequisites=selector.direct_prerequisites,
    )


def _observe_gate(
    selector: GateSelectorV1,
    latest_jobs: list[GitHubJobV1],
    statuses: list[GitHubCommitStatusV1],
    run: GitHubRunV1,
) -> ObservedGateV1:
    if isinstance(selector, ActionsJobGateSelectorV1):
        return _observe_actions_gate(selector, latest_jobs, run)
    return _observe_status_gate(selector, statuses, run)


def _complete_merge_elapsed(
    gates: list[ObservedGateV1],
    *,
    from_creation: bool,
) -> float | None:
    if not gates:
        return None
    values: list[float] = []
    for gate in gates:
        # A terminal failure is a check completion, never merge readiness. Only
        # selected successful gates set this clock; reporting jobs/run updates do not.
        if not gate.matched or gate.conclusion != "success":
            return None
        value = gate.elapsed_from_creation_seconds if from_creation else gate.elapsed_from_run_start_seconds
        if value is None:
            return None
        values.append(value)
    return max(values)


def _matching_rate(job: ObservedJobV1, rates: list[RunnerSkuRateV1]) -> RunnerSkuRateV1 | None:
    matches = [rate for rate in rates if rate.runner_label in job.runner_labels]
    if len(matches) > 1:
        raise ValueError(f"runner labels match multiple configured SKUs: {job.runner_labels}")
    return matches[0] if matches else None


def _runner_cost(jobs: list[ObservedJobV1], rates: list[RunnerSkuRateV1]) -> RunnerCostV1:
    costed = [job for job in jobs if job.wall_seconds is not None and job.rounded_minutes is not None]
    rates_by_label = {rate.runner_label: rate for rate in rates}
    if len(rates_by_label) != len(rates):
        raise ValueError("runner SKU rates must use distinct runner labels")
    rates_by_sku = {rate.sku: rate for rate in rates}
    if len(rates_by_sku) != len(rates):
        raise ValueError("runner SKU rates must use distinct SKU names")
    jobs_by_sku: dict[str, list[ObservedJobV1]] = {}
    unpriced_minutes = 0
    for job in costed:
        rate = _matching_rate(job, rates)
        if rate is None:
            if rates:
                unpriced_minutes += job.rounded_minutes or 0
            continue
        jobs_by_sku.setdefault(rate.sku, []).append(job)

    by_sku: list[RunnerSkuCostV1] = []
    for sku in sorted(jobs_by_sku):
        sku_jobs = jobs_by_sku[sku]
        rate = _matching_rate(sku_jobs[0], rates)
        assert rate is not None, "grouped SKU jobs must retain their matching rate"
        rounded_minutes = sum(job.rounded_minutes or 0 for job in sku_jobs)
        by_sku.append(
            RunnerSkuCostV1(
                sku=rate.sku,
                runner_label=rate.runner_label,
                usd_per_minute=rate.usd_per_minute,
                raw_runner_seconds=round(sum(job.wall_seconds or 0.0 for job in sku_jobs), 1),
                estimated_rounded_runner_minutes=rounded_minutes,
                rounding_waste_seconds=round(sum(job.rounding_waste_seconds or 0.0 for job in sku_jobs), 1),
                estimated_cost_usd=rate.usd_per_minute * rounded_minutes,
            )
        )
    priced_total = sum((item.estimated_cost_usd for item in by_sku), start=Decimal(0))
    return RunnerCostV1(
        raw_runner_seconds=round(sum(job.wall_seconds or 0.0 for job in costed), 1),
        estimated_rounded_runner_minutes=sum(job.rounded_minutes or 0 for job in costed),
        rounding_waste_seconds=round(sum(job.rounding_waste_seconds or 0.0 for job in costed), 1),
        billed_attempts=sorted({job.run_attempt for job in costed}),
        by_sku=by_sku,
        unpriced_rounded_runner_minutes=unpriced_minutes,
        estimated_cost_usd=priced_total if rates and unpriced_minutes == 0 else None,
    )


def _overlapping_runner_cost(
    overlapping_prior_runs: list[GitHubRunJobsV1],
    observed_at: datetime,
    runner_sku_rates: list[RunnerSkuRateV1],
) -> OverlappingRunnerCostV1:
    run_costs: list[OverlappingRunCostV1] = []
    for item in overlapping_prior_runs:
        observed_jobs = [_observe_job(job, item.run.created_at, observed_at) for job in item.jobs]
        run_costs.append(
            OverlappingRunCostV1(
                run_id=item.run.id,
                head_sha=item.run.head_sha,
                conclusion=item.run.conclusion,
                created_at=item.run.created_at,
                updated_at=item.run.updated_at,
                runner_cost=_runner_cost(observed_jobs, runner_sku_rates),
            )
        )
    priced_costs = [item.runner_cost.estimated_cost_usd for item in run_costs]
    all_runs_priced = bool(run_costs) and all(cost is not None for cost in priced_costs)
    return OverlappingRunnerCostV1(
        runs=run_costs,
        raw_runner_seconds=round(
            sum(item.runner_cost.raw_runner_seconds for item in run_costs),
            1,
        ),
        estimated_rounded_runner_minutes=sum(item.runner_cost.estimated_rounded_runner_minutes for item in run_costs),
        rounding_waste_seconds=round(
            sum(item.runner_cost.rounding_waste_seconds for item in run_costs),
            1,
        ),
        estimated_cost_usd=(
            sum((cost for cost in priced_costs if cost is not None), start=Decimal(0)) if all_runs_priced else None
        ),
    )


def build_report(
    *,
    repository: str,
    pull_request_number: int | None,
    run: GitHubRunV1,
    latest_jobs: list[GitHubJobV1],
    billing_jobs: list[GitHubJobV1],
    commit_statuses: list[GitHubCommitStatusV1],
    gate_selectors: list[GateSelectorV1],
    observed_at: datetime,
    overlapping_prior_runs: list[GitHubRunJobsV1] | None = None,
    collection_errors: list[str] | None = None,
    repository_signals: list[RepositorySignalV1] | None = None,
    extensions: dict[str, JsonValue] | None = None,
    runner_sku_rates: list[RunnerSkuRateV1] | None = None,
    test_selection: SelectionSectionV1 | None = None,
    lane_selection: LaneSelectionSectionV1 | None = None,
    job_dependencies: dict[str, list[str]] | None = None,
) -> CiObservabilityReportV1:
    errors = list(collection_errors or [])
    if not gate_selectors:
        errors.append("required gate metadata was not provided")

    timeline_start = run.created_at
    latest = [_observe_job(job, timeline_start, observed_at) for job in latest_jobs]
    billing = [_observe_job(job, timeline_start, observed_at) for job in billing_jobs]
    timed_latest = [job for job in latest if job.wall_seconds is not None]
    gates = [_observe_gate(selector, latest_jobs, commit_statuses, run) for selector in gate_selectors]
    missing = [gate.identity for gate in gates if not gate.matched]
    if missing:
        errors.append(f"required gates were not observed: {', '.join(missing)}")

    longest = max(timed_latest, key=lambda item: (item.wall_seconds or 0.0, item.name), default=None)
    rates = runner_sku_rates or []
    current_runner_cost = _runner_cost(billing, rates)
    overlapping_runner_cost = _overlapping_runner_cost(
        overlapping_prior_runs or [],
        observed_at,
        rates,
    )
    first_job_started_at = min(
        (job.started_at for job in latest_jobs if job.started_at is not None and job.conclusion != "skipped"),
        default=None,
    )
    merge_ready_from_creation = _complete_merge_elapsed(
        gates,
        from_creation=True,
    )
    job_admission_delay = _elapsed(run.created_at, first_job_started_at)
    merge_ready_after_admission = (
        round(merge_ready_from_creation - job_admission_delay, 1)
        if merge_ready_from_creation is not None
        and job_admission_delay is not None
        and merge_ready_from_creation >= job_admission_delay
        else None
    )
    status = CollectionStatus.COMPLETE if not errors else CollectionStatus.PARTIAL

    return CiObservabilityReportV1(
        collection_status=status,
        collection_errors=errors,
        provenance=RunProvenanceV1(
            repository=repository,
            workflow_name=run.name,
            run_id=run.id,
            run_attempt=run.run_attempt,
            head_sha=run.head_sha,
            pull_request_number=pull_request_number,
            workflow_created_at=run.created_at,
            workflow_run_started_at=run.run_started_at,
            observed_at=observed_at,
        ),
        latest_attempt_jobs=latest,
        billing_jobs=billing,
        required_gates=gates,
        merge_ready_from_creation_seconds=merge_ready_from_creation,
        merge_ready_from_run_start_seconds=_complete_merge_elapsed(
            gates,
            from_creation=False,
        ),
        workflow_initial_queue_seconds=_elapsed(run.created_at, run.run_started_at),
        workflow_job_admission_delay_seconds=job_admission_delay,
        merge_ready_after_job_admission_seconds=merge_ready_after_admission,
        longest_latest_job_name=longest.name if longest is not None else None,
        longest_latest_job_seconds=longest.wall_seconds if longest is not None else None,
        runner_cost=current_runner_cost,
        overlapping_prior_runner_cost=overlapping_runner_cost,
        repository_signals=repository_signals or [],
        extensions=extensions or {},
        test_selection=test_selection,
        lane_selection=lane_selection,
        critical_path=analyze(run.created_at, latest_jobs, job_dependencies,
                              [next((job.name for job in latest_jobs if job.id == gate.observed_job_id),
                                    gate.identity) for gate in gates]) if job_dependencies else None,
    )


def build_unavailable_report(
    *,
    repository: str,
    run_id: int,
    run_attempt: int,
    head_sha: str,
    pull_request_number: int | None,
    observed_at: datetime,
    error: str,
    repository_signals: list[RepositorySignalV1] | None = None,
) -> CiObservabilityReportV1:
    return CiObservabilityReportV1(
        collection_status=CollectionStatus.UNAVAILABLE,
        collection_errors=[error],
        provenance=RunProvenanceV1(
            repository=repository,
            workflow_name=None,
            run_id=run_id,
            run_attempt=run_attempt,
            head_sha=head_sha,
            pull_request_number=pull_request_number,
            workflow_created_at=None,
            workflow_run_started_at=None,
            observed_at=observed_at,
        ),
        latest_attempt_jobs=[],
        billing_jobs=[],
        required_gates=[],
        merge_ready_from_creation_seconds=None,
        merge_ready_from_run_start_seconds=None,
        workflow_initial_queue_seconds=None,
        workflow_job_admission_delay_seconds=None,
        merge_ready_after_job_admission_seconds=None,
        longest_latest_job_name=None,
        longest_latest_job_seconds=None,
        runner_cost=RunnerCostV1(
            raw_runner_seconds=0.0,
            estimated_rounded_runner_minutes=0,
            rounding_waste_seconds=0.0,
            billed_attempts=[],
        ),
        overlapping_prior_runner_cost=OverlappingRunnerCostV1(
            runs=[],
            raw_runner_seconds=0.0,
            estimated_rounded_runner_minutes=0,
            rounding_waste_seconds=0.0,
        ),
        repository_signals=repository_signals or [],
    )


def _mermaid_label(value: str) -> str:
    return value.replace("\n", " ").replace("\r", " ").replace(":", " -").replace("#", "").strip()


def _format_usd(value: Decimal) -> str:
    return format(value, "f")


def _gate_conclusion(report: CiObservabilityReportV1) -> str:
    if not report.required_gates or any(gate.conclusion is None for gate in report.required_gates):
        return "pending"
    if all(gate.conclusion == "success" for gate in report.required_gates):
        return "success"
    return "failure"


def sticky_snapshot(report: CiObservabilityReportV1) -> StickySnapshotV1:
    return StickySnapshotV1(
        run_id=report.provenance.run_id,
        run_attempt=report.provenance.run_attempt,
        completed_gates=sum(gate.completed_at is not None for gate in report.required_gates),
        observed_at=report.provenance.observed_at,
    )


def sticky_marker(key: str = "") -> str:
    """
    The hidden marker the sticky is found by: one sticky per pull request, or one per key.

    A repository whose observer reports several workflows keys each by workflow, so their reports
    do not overwrite one another. The key is reduced to a safe slug.
    """
    slug = re.sub(r"[^a-z0-9]+", "-", key.lower()).strip("-")
    return f"{STICKY_KEY_MARKER_PREFIX}{slug} -->" if slug else STICKY_MARKER


def _cost(report: CiObservabilityReportV1) -> list[str]:
    parts = [f"{report.runner_cost.estimated_rounded_runner_minutes} runner-min"]
    if report.runner_cost.estimated_cost_usd is not None:
        parts.append(f"${report.runner_cost.estimated_cost_usd:.2f}")
    return parts


def _readiness(report: CiObservabilityReportV1) -> str | None:
    """Merge readiness with its status mark; None when no required gate is configured."""
    if not report.required_gates:
        return None
    gates = report.merge_ready_from_creation_seconds
    if gates is not None:
        return f"✅ **Merge-ready in {format_seconds(gates)}**"
    label = _readiness_label(report)
    return f"❌ **{label.capitalize()}**" if label == "blocked" else f"⏳ **{label.capitalize()}**"


def _latency_summary(report: CiObservabilityReportV1) -> str:
    """One line standing in for the latency and cost report when it is collapsed."""
    gates = report.merge_ready_from_creation_seconds
    parts = [f"merge-ready in {format_seconds(gates)}" if gates is not None else _readiness_label(report)]
    return "⏱️ CI time and cost: " + " · ".join([*parts, *_cost(report)])


def _header(report: CiObservabilityReportV1) -> list[str]:
    """The brand mark, then one verdict line: readiness, what ran, and what it cost."""
    provenance = report.provenance
    workflow = f" · {markdown.inline(provenance.workflow_name)}" if provenance.workflow_name else ""
    verdict = [part for part in [_readiness(report)] if part is not None]
    if report.test_selection is not None:
        verdict.append(selection.headline(report.test_selection))
    if report.lane_selection is not None:
        verdict.append(lanes.headline(report.lane_selection))
    verdict.extend(_cost(report))
    return [
        f"[![{brand.CI_ESTA} report]({brand.CI_ESTA_BADGE})]({brand.CI_ESTA_URL})"
        f"{workflow} · {markdown.code(provenance.head_sha[:7])}",
        "",
        " · ".join(verdict),
        "",
    ]


def render_markdown(report: CiObservabilityReportV1, marker: str = STICKY_MARKER) -> str:
    """
    The sticky: a branded verdict, the selection sections there are, then latency and cost.

    With a selection section the latency report folds into one closed expander, so the sticky
    reads as the section an author acts on, with timings and cost one click away.
    """
    sections = []
    if report.test_selection is not None:
        sections.append(selection.render_selection_section(report.test_selection, report.provenance.repository))
    if report.lane_selection is not None:
        sections.append(lanes.render_lane_section(report.lane_selection, report.provenance.repository))
    if not sections:
        body = ["#### ⏱️ CI time and cost", "", *_latency_lines(report)]
    else:
        body = [
            *sections,
            f"<details><summary>{_latency_summary(report)}</summary>",
            "",
            *_latency_lines(report),
            "",
            "</details>",
        ]
    return "\n".join([*_header(report), *body, "", *_footer(report, marker)])


def _footer(report: CiObservabilityReportV1, marker: str = STICKY_MARKER) -> list[str]:
    run = report.provenance.run_id
    return [
        f"{SNAPSHOT_MARKER_PREFIX}{sticky_snapshot(report).model_dump_json()} -->",
        marker,
        f"<sub>🌴 Powered by [{brand.CI_ESTA}]({brand.CI_ESTA_URL}): {brand.TAGLINE} "
        f"· [Reading this report]({brand.CI_ESTA_DOCS_URL}) "
        f"· [run {run}](https://github.com/{report.provenance.repository}/actions/runs/{run}) "
        f"· schema `{report.schema_version}`</sub>",
    ]


def _readiness_label(report: CiObservabilityReportV1) -> str:
    return (
        "blocked"
        if any(gate.conclusion not in (None, "success") for gate in report.required_gates)
        else "gates running"
    )


def _latency_table(report: CiObservabilityReportV1) -> list[str]:
    """One row with the numbers a reader looks for; the rest of the section is detail."""
    cost = report.runner_cost
    gates = report.merge_ready_from_creation_seconds
    admission = report.workflow_job_admission_delay_seconds
    longest, longest_name = report.longest_latest_job_seconds, report.longest_latest_job_name
    columns = [
        ("Workflow", ":--", markdown.cell(report.provenance.workflow_name or "")),
        ("Merge-ready", "--:", format_seconds(gates) if gates is not None else _readiness_label(report)),
        ("First runner", "--:", f"after {format_seconds(admission)}" if admission is not None else ""),
        (
            "Longest job",
            ":--",
            f"{markdown.cell(longest_name)} · {format_seconds(longest)}"
            if longest is not None and longest_name is not None
            else "",
        ),
        ("Runner time", "--:", f"{cost.estimated_rounded_runner_minutes} min"),
        ("Cost", "--:", f"${_format_usd(cost.estimated_cost_usd)}" if cost.estimated_cost_usd is not None else "—"),
    ]
    shown = [column for column in columns if column[2]]
    return [
        "| " + " | ".join(header for header, _, _ in shown) + " |",
        "|" + "|".join(align for _, align, _ in shown) + "|",
        "| " + " | ".join(value for _, _, value in shown) + " |",
        "",
    ]


def _timeline(report: CiObservabilityReportV1) -> list[str]:
    timed_jobs = [
        job
        for job in report.latest_attempt_jobs
        if job.start_offset_seconds is not None
        and job.end_offset_seconds is not None
        and job.end_offset_seconds > job.start_offset_seconds
    ]
    merge_elapsed = report.merge_ready_from_creation_seconds
    if not timed_jobs and merge_elapsed is None:
        return []
    lines = [
        "```mermaid",
        '%%{init: {"gantt": {"barHeight": 24, "barGap": 7, "topPadding": 50, '
        '"leftPadding": 250, "fontSize": 13, "sectionFontSize": 14}}}%%',
        "gantt",
        "    title CI jobs from workflow creation",
        "    dateFormat X",
        "    axisFormat %M:%S",
    ]
    if merge_elapsed is not None:
        lines += ["    section Merge", f"    required gate elapsed :crit, merge_gate, 0, {math.ceil(merge_elapsed)}"]
    admission = report.workflow_job_admission_delay_seconds
    if admission is not None and admission > 0:
        lines += ["    section Admission", f"    no runner assigned to this run :admission, 0, {math.ceil(admission)}"]
    if timed_jobs:
        lines.append("    section Jobs")
    gate_job_ids = {gate.observed_job_id for gate in report.required_gates if gate.observed_job_id is not None}
    for index, job in enumerate(sorted(timed_jobs, key=lambda item: (item.start_offset_seconds or 0.0, item.name))):
        label = _mermaid_label(job.name)
        if job.timing_status == TimingStatus.ACCRUED:
            label += " (active at snapshot)"
        path = report.critical_path
        on_path = job.name in path.observed_path if path and path.status == "complete" else job.job_id in gate_job_ids
        critical = "crit, " if on_path else ""
        lines.append(
            f"    {label} :{critical}job_{index}, "
            f"{int(job.start_offset_seconds or 0)}, {int(job.end_offset_seconds or 0)}"
        )
    merge_bar = (
        "Red bar: workflow creation to required gates done."
        if merge_elapsed is not None
        else "A red bar appears once all required gates complete."
    )
    return [
        *lines,
        "```",
        "",
        f"<sub>{merge_bar} Bars are observed API timestamps; see the dependency analysis below when configured.</sub>",
        "",
    ]


def _critical_path(report: CiObservabilityReportV1) -> list[str]:
    path = report.critical_path
    if path is None:
        return []
    if path.status != "complete":
        return [f"Critical path unavailable: {markdown.cell(path.reason)}", ""]
    return [
        "### Critical path",
        "",
        f"Observed dependency chain ({format_seconds(path.elapsed_seconds)}): "
        + " → ".join(markdown.cell(name) for name in path.observed_path),
        "",
        f"Execution-only CPM ({format_seconds(path.execution_seconds)}): "
        + " → ".join(markdown.cell(name) for name in path.execution_path),
        "",
        "| Job | Execution (s) | Delay after prerequisites (s) | Execution slack (s) |",
        "| --- | ---: | ---: | ---: |",
        *[f"| {markdown.cell(n.name)} | {n.execution_seconds:g} | {n.delay_seconds:g} | {n.slack_seconds:g} |"
          for n in path.nodes],
        "",
        "Delay includes scheduling, runner admission and other waits; it is not isolated queue time. "
        "Execution CPM holds measured durations constant and excludes those delays. "
        "The declared DAG must cover every prerequisite; this analysis does not assert validation success.",
        "",
    ]


def _overlap(report: CiObservabilityReportV1) -> list[str]:
    cost, overlap = report.runner_cost, report.overlapping_prior_runner_cost
    if not overlap.runs:
        return []
    combined_minutes = cost.estimated_rounded_runner_minutes + overlap.estimated_rounded_runner_minutes
    combined_raw_minutes = (cost.raw_runner_seconds + overlap.raw_runner_seconds) / 60
    run_word = "run" if len(overlap.runs) == 1 else "runs"
    lines = [
        f"> Cross-run overlap: **{len(overlap.runs)} prior same-PR/workflow {run_word}** "
        f"overlapped this run's creation and consumed an estimated "
        f"**{overlap.estimated_rounded_runner_minutes} rounded min** "
        f"({overlap.raw_runner_seconds / 60:.1f} raw min). "
        f"Combined observed estimate: **{combined_minutes} rounded min** "
        f"from **{combined_raw_minutes:.1f} raw min**.",
        "> These are separate run IDs and are not included in this run's runner time.",
    ]
    if cost.estimated_cost_usd is not None and overlap.estimated_cost_usd is not None:
        combined_cost = cost.estimated_cost_usd + overlap.estimated_cost_usd
        lines.append(f"> Combined observed cost from configured rates: **${_format_usd(combined_cost)}**.")
    rows = [
        f"| [run {item.run_id}](https://github.com/{report.provenance.repository}/actions/runs/{item.run_id}) | "
        f"{markdown.cell(item.conclusion or 'active')} | "
        f"{item.runner_cost.raw_runner_seconds / 60:.1f} min | "
        f"{item.runner_cost.estimated_rounded_runner_minutes} |"
        for item in overlap.runs
    ]
    return [
        *lines,
        "",
        *_details(
            "Overlapping prior-run estimate",
            [
                "| prior run | conclusion | raw | rounded min |",
                "|---|---|--:|--:|",
                *rows,
                "",
                "_Overlap means the prior run's observed lifetime crossed this run's creation; "
                "the API does not expose concurrency-group causality._",
            ],
        ),
    ]


def _cost_details(report: CiObservabilityReportV1) -> list[str]:
    cost = report.runner_cost
    billed_seconds = cost.estimated_rounded_runner_minutes * 60
    waste_percent = (cost.rounding_waste_seconds / billed_seconds * 100) if billed_seconds else 0.0
    body = [
        f"Estimated runner usage for this run: **{cost.estimated_rounded_runner_minutes} rounded min** "
        f"from **{cost.raw_runner_seconds / 60:.1f} raw min**; **{cost.rounding_waste_seconds / 60:.1f} min "
        f"({waste_percent:.0f}%)** is per-job rounding.",
        "",
    ]
    if cost.estimated_cost_usd is not None:
        body += [
            f"Estimated runner cost at configured rates: **${_format_usd(cost.estimated_cost_usd)}**.",
            "",
            "| runner SKU | rounded min | USD/min | estimated cost |",
            "|---|--:|--:|--:|",
            *(
                f"| {markdown.cell(item.sku)} | {item.estimated_rounded_runner_minutes} | "
                f"${_format_usd(item.usd_per_minute)} | ${_format_usd(item.estimated_cost_usd)} |"
                for item in cost.by_sku
            ),
            "",
        ]
    elif cost.unpriced_rounded_runner_minutes:
        body += [
            f"_Exact dollar cost withheld: {cost.unpriced_rounded_runner_minutes} rounded runner min "
            "did not match a configured runner label._",
            "",
        ]
    if len(cost.billed_attempts) > 1:
        body += [f"_Includes workflow attempts: {', '.join(str(item) for item in cost.billed_attempts)}._", ""]
    body += ["| job | attempt | wall | rounded min | save 1 min | headroom |", "|---|--:|--:|--:|--:|--:|"]
    for job in sorted(
        (item for item in report.billing_jobs if item.rounded_minutes is not None),
        key=lambda item: (item.rounded_minutes or 0, item.wall_seconds or 0.0, item.name),
        reverse=True,
    ):
        save = "remove/consolidate" if job.rounded_minutes == 1 else f"{job.seconds_to_save_minute or 0.0:.0f}s"
        body.append(
            f"| {markdown.cell(job.name)} | {job.run_attempt} | {job.wall_seconds or 0.0:.0f}s | "
            f"{job.rounded_minutes} | {save} | {job.seconds_until_next_minute or 0.0:.0f}s |"
        )
    body += [
        "",
        "_The organization billing ledger is authoritative; this estimate applies "
        "a per-job minute ceiling to GitHub timestamps._",
    ]
    return _details("Runner minutes and cost by runner and job", body)


def _step_details(report: CiObservabilityReportV1) -> list[str]:
    if not report.latest_attempt_jobs:
        return []
    rows = []
    for job in sorted(report.latest_attempt_jobs, key=lambda item: item.wall_seconds or 0, reverse=True):
        slowest = max(
            (step for step in job.steps if step.wall_seconds is not None),
            key=lambda step: step.wall_seconds or 0,
            default=None,
        )
        url = f"https://github.com/{report.provenance.repository}/actions/runs/{report.provenance.run_id}/job/{job.job_id}"
        job_name = markdown.cell(markdown.code(job.name))
        step_name = markdown.cell(markdown.code(slowest.name)) if slowest else "unavailable"
        wall = f"{job.wall_seconds:.0f}s ({job.timing_status.value})" if job.wall_seconds is not None else "unavailable"
        step_wall = f"{slowest.wall_seconds:.0f}s ({slowest.timing_status.value})" if slowest else "unavailable"
        rows.append(f"| [{job_name}]({url}) | {markdown.cell(job.conclusion or job.status)} | {wall} | {step_name} | {step_wall} |")
    return _details("Slowest step in each job", [
        "| job | result | job time | slowest timed step | step time |",
        "|---|---|--:|---|--:|",
        *rows,
        "",
        "_Latest attempt only. All observed steps are retained in the JSON report. "
        "Unavailable timestamps are not zero; accrued time is measured at the snapshot. "
        "Step times explain job time and are not added to runner usage._",
    ])


def _prerequisites(report: CiObservabilityReportV1) -> list[str]:
    rows = [
        f"| {markdown.cell(gate.display_name)} | "
        f"{markdown.cell(prerequisite.display_name or prerequisite.job_id)} | {markdown.cell(prerequisite.result)} |"
        for gate in report.required_gates
        for prerequisite in gate.direct_prerequisites
    ]
    if not rows:
        return []
    return _details(
        "Required gates and their direct prerequisites",
        [
            "| gate | direct prerequisite | result |",
            "|---|---|---|",
            *rows,
            "",
            "_These are consumer-exported direct edges, not a reconstructed transitive DAG or a causal critical path._",
        ],
    )


def _details(summary: str, body: list[str]) -> list[str]:
    return ["<details>", f"<summary>{summary}</summary>", "", *body, "", "</details>", ""]


def _latency_lines(report: CiObservabilityReportV1) -> list[str]:
    """
    Latency and cost: one summary row, the timeline, then detail behind expanders.

    The pytest timing signal is left out beside a test-selection section, which shows the same
    wall and test time in its own summary row.
    """
    signals = [
        signal
        for signal in report.repository_signals
        if report.test_selection is None or signal.key != PYTEST_TIMING_SIGNAL
    ]
    lines = [
        *_latency_table(report),
        *_overlap(report),
        *_timeline(report),
        *_critical_path(report),
        *_cost_details(report),
        *_step_details(report),
        *_prerequisites(report),
        *(f"_{markdown.inline(signal.label)}: {markdown.inline(signal.value)}._" for signal in signals),
        *([""] if signals else []),
    ]
    if report.collection_errors:
        lines.append("> Partial snapshot: " + "; ".join(report.collection_errors))
    while lines and not lines[-1]:
        lines.pop()
    return lines


def render_prometheus(report: CiObservabilityReportV1) -> str:
    conclusion = _gate_conclusion(report)
    labels = f'gate_conclusion="{conclusion}",schema_version="v1"'
    values = [
        ("ci_merge_ready_from_creation_seconds", report.merge_ready_from_creation_seconds),
        ("ci_merge_ready_from_run_start_seconds", report.merge_ready_from_run_start_seconds),
        ("ci_workflow_initial_queue_seconds", report.workflow_initial_queue_seconds),
        (
            "ci_workflow_job_admission_delay_seconds",
            report.workflow_job_admission_delay_seconds,
        ),
        (
            "ci_merge_ready_after_job_admission_seconds",
            report.merge_ready_after_job_admission_seconds,
        ),
        ("ci_longest_latest_job_seconds", report.longest_latest_job_seconds),
        ("ci_raw_runner_seconds", report.runner_cost.raw_runner_seconds),
        (
            "ci_estimated_rounded_runner_minutes",
            float(report.runner_cost.estimated_rounded_runner_minutes),
        ),
        ("ci_rounding_waste_seconds", report.runner_cost.rounding_waste_seconds),
        (
            "ci_estimated_runner_cost_usd",
            float(report.runner_cost.estimated_cost_usd) if report.runner_cost.estimated_cost_usd is not None else None,
        ),
        (
            "ci_overlapping_prior_run_count",
            float(len(report.overlapping_prior_runner_cost.runs)),
        ),
        (
            "ci_overlapping_prior_raw_runner_seconds",
            report.overlapping_prior_runner_cost.raw_runner_seconds,
        ),
        (
            "ci_overlapping_prior_estimated_rounded_runner_minutes",
            float(report.overlapping_prior_runner_cost.estimated_rounded_runner_minutes),
        ),
    ]
    lines: list[str] = []
    for metric, value in values:
        if value is None:
            continue
        lines.append(f"# TYPE {metric} gauge")
        lines.append(f"{metric}{{{labels}}} {float(value)}")
    return "\n".join(lines) + "\n"
