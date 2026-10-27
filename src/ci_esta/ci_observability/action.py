"""
GitHub composite-action adapter for the shared CI observability reporter.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pytest_selective.impact_models import SelectionExplanation

    from ci_esta.ci_observability.python_selection_models import LaneSelectionSectionV1, SelectionSectionV1

from pydantic import BaseModel, ConfigDict, Field, JsonValue, TypeAdapter

from ci_esta.ci_observability.enrichment.profiles import pytest_timings
from ci_esta.ci_observability.github import GitHubActionsClient
from ci_esta.ci_observability.impact import ImpactComparison, collect_impact
from ci_esta.ci_observability.models import (
    CiObservabilityReportV1,
    CommitStatusGateSelectorV1,
    FullSuiteReferenceV1,
    GateSelectorV1,
    GitHubJobV1,
    GitHubRunJobsV1,
    GitHubRunV1,
    RepositorySignalV1,
    RunnerSkuRateV1,
)
from ci_esta.ci_observability.report import (
    build_report,
    build_unavailable_report,
    render_markdown,
    render_prometheus,
    sticky_marker,
    sticky_snapshot,
)
from ci_esta.ci_observability.work_selection import WorkSelectionV1

GATE_SELECTORS_ADAPTER = TypeAdapter(list[GateSelectorV1])
EXTENSIONS_ADAPTER = TypeAdapter(dict[str, JsonValue])
REPOSITORY_SIGNALS_ADAPTER = TypeAdapter(list[RepositorySignalV1])
RUNNER_SKU_RATES_ADAPTER = TypeAdapter(list[RunnerSkuRateV1])
#: Recent comparable full-suite runs the saving takes the median of, so one odd run cannot set it.
REFERENCE_SAMPLE = 5
#: A reference counts only while its suite has about the size of this run's.
REFERENCE_SIZE_TOLERANCE = 0.1


class ActionConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    repository: str
    github_token: str
    workflow_source_token: str = Field(default="", repr=False)
    api_url: str
    run_id: int
    run_attempt: int
    commit_sha: str
    pull_request_number: int | None
    gate_selectors: list[GateSelectorV1]
    repository_signals: list[RepositorySignalV1]
    extensions: dict[str, JsonValue]
    report_output: Path
    markdown_output: Path
    prometheus_output: Path
    post_sticky: bool
    append_summary: bool
    runner_sku_rates: list[RunnerSkuRateV1] = Field(default_factory=list)
    #: Each artifact holds one JSON file. Empty disables the section or the reference.
    test_selection_artifact: str = ""
    full_suite_reference_artifact: str = ""
    full_suite_reference_output: Path = Path("ci-full-suite-reference.json")
    #: The run's pytest-selective lane plan; empty disables the lane section.
    lane_selection_artifact: str = ""
    #: Keys the sticky, so several observed workflows each keep their own comment.
    sticky_key: str = ""
    sticky_workflow: str = ""
    work_selection_artifact: str = ""
    impact_comparisons: list[ImpactComparison] = Field(default_factory=list, max_length=12)
    job_dependencies: dict[str, list[str]] = Field(default_factory=dict)
    analyze_critical_path: bool = False

    @classmethod
    def from_environment(cls) -> "ActionConfig":
        pull_request = os.environ.get("INPUT_PULL_REQUEST_NUMBER", "").strip()
        extensions_file = os.environ.get("INPUT_EXTENSIONS_FILE", "").strip()
        repository_signals_file = os.environ.get("INPUT_REPOSITORY_SIGNALS_FILE", "").strip()
        extensions: dict[str, JsonValue] = {}
        repository_signals: list[RepositorySignalV1] = []
        if extensions_file:
            extensions = EXTENSIONS_ADAPTER.validate_json(Path(extensions_file).read_bytes())
        if repository_signals_file:
            repository_signals = REPOSITORY_SIGNALS_ADAPTER.validate_json(Path(repository_signals_file).read_bytes())
        return cls(
            repository=os.environ["GITHUB_REPOSITORY"],
            github_token=os.environ["INPUT_GITHUB_TOKEN"],
            workflow_source_token=os.environ.get("INPUT_WORKFLOW_SOURCE_TOKEN", ""),
            api_url=os.environ.get("GITHUB_API_URL", "https://api.github.com"),
            run_id=int(os.environ["INPUT_RUN_ID"]),
            run_attempt=int(os.environ["INPUT_RUN_ATTEMPT"]),
            commit_sha=os.environ["INPUT_COMMIT_SHA"],
            pull_request_number=int(pull_request) if pull_request else None,
            gate_selectors=GATE_SELECTORS_ADAPTER.validate_json(os.environ.get("INPUT_REQUIRED_GATES_JSON", "[]")),
            repository_signals=repository_signals,
            extensions=extensions,
            report_output=Path(os.environ["INPUT_REPORT_OUTPUT"]),
            markdown_output=Path(os.environ["INPUT_MARKDOWN_OUTPUT"]),
            prometheus_output=Path(os.environ["INPUT_PROMETHEUS_OUTPUT"]),
            post_sticky=os.environ.get("INPUT_POST_STICKY", "true").lower() == "true",
            append_summary=os.environ.get("INPUT_APPEND_SUMMARY", "true").lower() == "true",
            runner_sku_rates=RUNNER_SKU_RATES_ADAPTER.validate_json(
                os.environ.get("INPUT_RUNNER_SKU_RATES_JSON", "[]")
            ),
            test_selection_artifact=os.environ.get("INPUT_TEST_SELECTION_ARTIFACT", "").strip(),
            full_suite_reference_artifact=os.environ.get("INPUT_FULL_SUITE_REFERENCE_ARTIFACT", "").strip(),
            full_suite_reference_output=Path(
                os.environ.get("INPUT_FULL_SUITE_REFERENCE_OUTPUT", "ci-full-suite-reference.json")
            ),
            lane_selection_artifact=os.environ.get("INPUT_LANE_SELECTION_ARTIFACT", "").strip(),
            work_selection_artifact=os.environ.get("INPUT_WORK_SELECTION_ARTIFACT", "").strip(),
            impact_comparisons=TypeAdapter(list[ImpactComparison]).validate_json(
                os.environ.get("INPUT_IMPACT_COMPARISONS_JSON", "[]")),
            sticky_key=os.environ.get("INPUT_STICKY_KEY", "").strip(),
            sticky_workflow=os.environ.get("INPUT_STICKY_WORKFLOW", "").strip(),
            job_dependencies=TypeAdapter(dict[str, list[str]]).validate_json(
                os.environ.get("INPUT_JOB_DEPENDENCIES_JSON", "{}")),
            analyze_critical_path=os.environ.get("INPUT_ANALYZE_CRITICAL_PATH", "false").lower() == "true",
        )


def _write_outputs(config: ActionConfig, report_json: str, markdown: str, prometheus: str) -> None:
    for path, body in (
        (config.report_output, report_json),
        (config.markdown_output, markdown),
        (config.prometheus_output, prometheus),
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body)

    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if config.append_summary and summary_path:
        with Path(summary_path).open("a") as summary:
            summary.write(markdown + "\n")

    output_path = os.environ.get("GITHUB_OUTPUT")
    if output_path:
        with Path(output_path).open("a") as output:
            output.write(f"report-file={config.report_output}\n")
            output.write(f"markdown-file={config.markdown_output}\n")
            output.write(f"prometheus-file={config.prometheus_output}\n")


def _write_reference(config: ActionConfig, reference: FullSuiteReferenceV1) -> None:
    """Leave the reference for the action's upload step, which only runs when this output is set."""
    config.full_suite_reference_output.parent.mkdir(parents=True, exist_ok=True)
    config.full_suite_reference_output.write_text(reference.model_dump_json(indent=2) + "\n")
    output_path = os.environ.get("GITHUB_OUTPUT")
    if output_path:
        with Path(output_path).open("a") as output:
            output.write(f"full-suite-reference-file={config.full_suite_reference_output}\n")


def _explanation(client: GitHubActionsClient, name: str, run: GitHubRunV1) -> SelectionExplanation | None:
    """This run's newest explanation, or None when there is none or its plan fell back."""
    for artifact in client.list_artifacts(name, run_id=run.id):
        if artifact.from_same_repository:
            from pytest_selective.impact_models import ExplanationUnavailable, SelectionExplanation
            explanation = TypeAdapter(SelectionExplanation | ExplanationUnavailable).validate_json(client.read_single_file_artifact(artifact.id))
            return explanation if isinstance(explanation, SelectionExplanation) else None
    return None


def _references(
    client: GitHubActionsClient, name: str, run: GitHubRunV1, total_files: int
) -> list[FullSuiteReferenceV1]:
    """
    The newest comparable references from other same-repository runs, newest first.

    An unreadable reference (another format, a broken upload) is skipped rather than hiding the
    ones behind it, and so is one whose suite size no longer matches this run's.
    """
    references: list[FullSuiteReferenceV1] = []
    candidates = [artifact for artifact in client.list_artifacts(name)
                  if artifact.from_same_repository and artifact.workflow_run is not None
                  and artifact.workflow_run.id != run.id]
    while candidates and len(references) < REFERENCE_SAMPLE:
        count = REFERENCE_SAMPLE - len(references)
        batch, candidates = candidates[:count], candidates[count:]
        for artifact, content in zip(batch, client.read_artifacts([item.id for item in batch]), strict=True):
            try:
                if isinstance(content, Exception):
                    raise content
                reference = FullSuiteReferenceV1.model_validate_json(content)
            except Exception as error:
                print(f"::warning::Skipped unreadable full-suite reference {artifact.id}: {error}")
                continue
            if abs(reference.total_files - total_files) <= REFERENCE_SIZE_TOLERANCE * total_files:
                references.append(reference)
    return references


def _test_selection(client: GitHubActionsClient, config: ActionConfig, run: GitHubRunV1) -> SelectionSectionV1 | None:
    """
    The sticky's test-selection section, when this run planned its tests with an explanation.

    Only reports that post the sticky render it. Anything missing leaves the section out or its
    saving unknown, with a warning; it never costs the rest of the report.
    """
    if not (config.post_sticky and config.test_selection_artifact):
        return None
    try:
        explanation = _explanation(client, config.test_selection_artifact, run)
    except Exception as error:
        print(f"::warning::Test selection section unavailable: {error}")
        return None
    if explanation is None:
        return None
    references: list[FullSuiteReferenceV1] = []
    if config.full_suite_reference_artifact:
        try:
            references = _references(client, config.full_suite_reference_artifact, run, explanation.total)
        except Exception as error:
            print(f"::warning::Full-suite references unavailable; the saving is unknown: {error}")
    from ci_esta.ci_observability.python_selection_models import SelectionSectionV1
    return SelectionSectionV1(explanation=explanation, pytest=pytest_timings(config.extensions), references=references)


def _lane_selection(
    client: GitHubActionsClient, config: ActionConfig, run: GitHubRunV1, latest_jobs: list[GitHubJobV1]
) -> LaneSelectionSectionV1 | None:
    """
    The sticky's lane section, when this run uploaded a pytest-selective lane plan.

    A fork's upload is ignored, like its selection explanation. What skipping saved is read from
    the default branch's last green push run; without one the section still renders, unpriced.
    Anything missing is a warning; it never costs the rest of the report.
    """
    if not config.lane_selection_artifact:
        return None
    try:
        artifact = next(
            (
                artifact
                for artifact in client.list_artifacts(config.lane_selection_artifact, run_id=run.id)
                if artifact.from_same_repository
            ),
            None,
        )
        if artifact is None:
            return None
        from pytest_selective.ci import LanePlan

        from ci_esta.ci_observability.lanes import skipped_reference
        from ci_esta.ci_observability.python_selection_models import LaneSelectionSectionV1
        plan = LanePlan.model_validate_json(client.read_single_file_artifact(artifact.id))
    except Exception as error:
        print(f"::warning::Lane selection section unavailable: {error}")
        return None
    if all(plan.lanes.values()) or run.workflow_id is None:
        return LaneSelectionSectionV1(plan=plan)
    try:
        reference_run = client.latest_successful_push_run(run.workflow_id, client.default_branch())
        reference = (
            skipped_reference(latest_jobs, reference_run, client.list_jobs(reference_run.id, include_all_attempts=False))
            if reference_run is not None and reference_run.id != run.id
            else None
        )
    except Exception as error:
        print(f"::warning::Skipped-lane cost unavailable: {error}")
        reference = None
    return LaneSelectionSectionV1(plan=plan, reference=reference)


def _work_selection(client: GitHubActionsClient, config: ActionConfig, run: GitHubRunV1) -> WorkSelectionV1 | None:
    if not config.work_selection_artifact:
        return None
    try:
        for artifact in client.list_artifacts(config.work_selection_artifact, run_id=run.id):
            if not artifact.from_same_repository:
                continue
            plan = WorkSelectionV1.model_validate_json(client.read_single_file_artifact(artifact.id))
            # Artifacts from an earlier attempt or another revision cannot explain this run.
            if (plan.run_id, plan.run_attempt, plan.head_sha) != (run.id, run.run_attempt, run.head_sha):
                raise ValueError("work selection does not match source run/attempt/head")
            return plan
    except Exception as error:
        print(f"::warning::Work selection section unavailable: {error}")
    return None


def _own_reference(
    report: CiObservabilityReportV1, config: ActionConfig, run: GitHubRunV1, observed_at: datetime
) -> FullSuiteReferenceV1 | None:
    """
    This run's timings as a future baseline, when it is one.

    It must be green, so a startup crash cannot pose as a fast suite, and its change must have
    reached every test, so nothing forced the full suite: consumers force it for coverage,
    schedules, dispatches and labels, all of which time something other than a PR run.
    """
    section = report.test_selection
    if section is None or not config.full_suite_reference_artifact or run.head_branch is None:
        return None
    pytest = section.pytest
    if not section.explanation.natural_full_suite or pytest is None:
        return None
    if not pytest.wall_seconds or not pytest.total_test_seconds:
        return None
    gates = report.required_gates
    if not gates or not all(gate.matched and gate.conclusion == "success" for gate in gates):
        return None
    return FullSuiteReferenceV1(
        timings=pytest,
        total_files=section.explanation.total,
        run_id=run.id,
        head_branch=run.head_branch,
        recorded_at=observed_at,
    )


def run(config: ActionConfig, observed_at: datetime) -> int:
    started = perf_counter()
    client = GitHubActionsClient(config.repository, config.github_token, config.api_url,
                                workflow_source_token=config.workflow_source_token)
    errors: list[str] = []
    reference_to_record: FullSuiteReferenceV1 | None = None
    try:
        run_metadata = client.get_run(config.run_id)
        older_attempt = run_metadata.run_attempt != config.run_attempt
        if older_attempt:
            run_metadata = client.get_run(config.run_id, run_attempt=config.run_attempt)
        if run_metadata.run_attempt != config.run_attempt or (
            config.commit_sha and run_metadata.head_sha != config.commit_sha
        ):
            raise ValueError("source run attempt/head does not match the requested report identity")
        job_dependencies = config.job_dependencies
        try:
            latest_jobs = client.list_jobs(config.run_id, include_all_attempts=False)
            needs_exact_attempt = older_attempt or any(job.run_attempt != config.run_attempt for job in latest_jobs)
            if needs_exact_attempt:
                latest_jobs = client.list_jobs(
                    config.run_id, include_all_attempts=False, run_attempt=config.run_attempt
                )
            if any(job.run_attempt != config.run_attempt for job in latest_jobs):
                raise ValueError("job attempts do not match the requested report identity")
            # The generic job listing can lag a workflow_run:completed event.
            # Use the exact-attempt endpoint once; preserve the useful original
            # snapshot if refreshing fails, with its inconsistency made visible.
            if not needs_exact_attempt and run_metadata.status == "completed" and (
                not latest_jobs or any(job.status != "completed" for job in latest_jobs)
            ):
                try:
                    refreshed = client.list_jobs(
                        config.run_id, include_all_attempts=False, run_attempt=config.run_attempt
                    )
                    if latest_jobs and not refreshed:
                        raise ValueError("refreshed job list is empty")
                    if any(job.run_attempt != config.run_attempt for job in refreshed):
                        raise ValueError("refreshed job attempts do not match the requested report identity")
                    latest_jobs = refreshed
                except Exception as error:
                    errors.append(f"completed source run job refresh unavailable: {error}")
            if run_metadata.status == "completed" and any(job.status != "completed" for job in latest_jobs):
                errors.append("completed source run still has nonterminal jobs after exact-attempt refresh")
        except Exception as error:
            latest_jobs = []
            errors.append(f"latest-attempt jobs unavailable: {error}")
        if config.analyze_critical_path and not job_dependencies:
            try:
                job_dependencies = client.workflow_dependencies(run_metadata, latest_jobs)
            except Exception as error:
                errors.append(f"critical-path graph unavailable: {error}")
        try:
            billing_jobs = client.list_jobs(config.run_id, include_all_attempts=True)
        except Exception as error:
            billing_jobs = latest_jobs
            errors.append(f"all-attempt jobs unavailable; latest attempt only: {error}")
        # A later all-attempt listing must not downgrade terminal evidence from
        # the same job/attempt back to an accrued duration or a running verdict.
        completed_jobs = {(job.id, job.run_attempt): job for job in latest_jobs if job.status == "completed"}
        billing_jobs = [
            completed_jobs.get((job.id, job.run_attempt), job) if job.status != "completed" else job
            for job in billing_jobs
        ]
        overlapping_prior_runs: list[GitHubRunJobsV1] = []
        if (
            config.pull_request_number is not None
            and run_metadata.workflow_id is not None
            and run_metadata.head_branch is not None
        ):
            try:
                prior_runs = client.list_overlapping_prior_runs(
                    run_metadata,
                    config.pull_request_number,
                )
                for prior_run in prior_runs:
                    try:
                        prior_jobs = client.list_jobs(
                            prior_run.id,
                            include_all_attempts=True,
                        )
                    except Exception as error:
                        errors.append(f"overlapping prior run {prior_run.id} jobs unavailable: {error}")
                        continue
                    overlapping_prior_runs.append(GitHubRunJobsV1(run=prior_run, jobs=prior_jobs))
            except Exception as error:
                errors.append(f"overlapping prior runs unavailable: {error}")
        test_selection = _test_selection(client, config, run_metadata)
        lane_selection = _lane_selection(client, config, run_metadata, latest_jobs)
        statuses = []
        if any(isinstance(selector, CommitStatusGateSelectorV1) for selector in config.gate_selectors):
            try:
                statuses = client.list_commit_statuses(run_metadata.head_sha)
            except Exception as error:
                errors.append(f"commit statuses unavailable: {error}")
        report = build_report(
            repository=config.repository,
            pull_request_number=config.pull_request_number,
            run=run_metadata,
            latest_jobs=latest_jobs,
            billing_jobs=billing_jobs,
            commit_statuses=statuses,
            gate_selectors=config.gate_selectors,
            observed_at=observed_at,
            overlapping_prior_runs=overlapping_prior_runs,
            collection_errors=errors,
            repository_signals=config.repository_signals,
            extensions=config.extensions,
            runner_sku_rates=config.runner_sku_rates,
            test_selection=test_selection,
            lane_selection=lane_selection,
            job_dependencies=job_dependencies,
        )
        from ci_esta.ci_observability.efficiency import collect_measurements
        measurements, measurement_errors = collect_measurements(client, run_metadata, latest_jobs)
        report = report.model_copy(update={"measurements": measurements, "measurement_errors": measurement_errors,
                                           "work_selection": _work_selection(client, config, run_metadata),
                                           "measured_impact": collect_impact(client, config.impact_comparisons)})
        reference_to_record = _own_reference(report, config, run_metadata, observed_at)
    except Exception as error:
        report = build_unavailable_report(
            repository=config.repository,
            run_id=config.run_id,
            run_attempt=config.run_attempt,
            head_sha=config.commit_sha,
            pull_request_number=config.pull_request_number,
            observed_at=observed_at,
            error=f"report collection unavailable: {error}",
            repository_signals=config.repository_signals,
        )

    collected = perf_counter()
    report_json = report.model_dump_json(indent=2) + "\n"
    marker = sticky_marker(config.sticky_key)
    markdown = render_markdown(report, marker)
    prometheus = render_prometheus(report)
    _write_outputs(config, report_json, markdown, prometheus)
    if reference_to_record is not None:
        _write_reference(config, reference_to_record)

    rendered = perf_counter()
    if (config.post_sticky and config.pull_request_number is not None
            and (not config.sticky_workflow or report.provenance.workflow_name == config.sticky_workflow)):
        try:
            client.upsert_sticky(
                config.pull_request_number,
                marker,
                markdown,
                sticky_snapshot(report),
            )
        except Exception as error:
            print(f"::warning::CI observability sticky unavailable: {error}")
    client.close()
    print(json.dumps({"reporter_seconds": {"collect": round(collected - started, 3),
                                           "render": round(rendered - collected, 3),
                                           "publish": round(perf_counter() - rendered, 3)}}))
    print(
        json.dumps(
            {
                "schema_version": report.schema_version,
                "collection_status": report.collection_status,
                "run_id": report.provenance.run_id,
            }
        )
    )
    return 0


def main() -> int:
    return run(ActionConfig.from_environment(), datetime.now(timezone.utc))


if __name__ == "__main__":  # pragma: no cover - exercised by the action wrapper
    raise SystemExit(main())
