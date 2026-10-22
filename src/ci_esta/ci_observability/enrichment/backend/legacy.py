"""Temporary BE-751 bridge for gigaverse-backend's existing Grafana metric names.

The sticky and authoritative artifact use CI-esta's shared contract.
This module exists only so dashboard migration can happen without a telemetry
gap; BE-751 removes it after the queries move to shared metric names.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from ci_esta.ci_observability.enrichment.backend.models import (
    RUNNER_TEST_SHARD_PREFIX,
    BackendExtensions,
)


class SharedObservedJob(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    name: str
    wall_seconds: float | None = None
    start_offset_seconds: float | None = None
    end_offset_seconds: float | None = None


class SharedObservedGate(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    conclusion: str | None = None


class SharedRunnerCost(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    raw_runner_seconds: float
    estimated_rounded_runner_minutes: int
    rounding_waste_seconds: float


class SharedReport(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    latest_attempt_jobs: list[SharedObservedJob]
    required_gates: list[SharedObservedGate]
    merge_ready_from_creation_seconds: float | None = None
    merge_ready_from_run_start_seconds: float | None = None
    workflow_initial_queue_seconds: float | None = None
    longest_latest_job_seconds: float | None = None
    runner_cost: SharedRunnerCost


def _job(
    report: SharedReport,
    name: str,
) -> SharedObservedJob | None:
    return next(
        (item for item in report.latest_attempt_jobs if item.name == name),
        None,
    )


def _job_seconds(report: SharedReport, name: str) -> float | None:
    job = _job(report, name)
    return job.wall_seconds if job else None


def _runner_lane_seconds(report: SharedReport) -> float | None:
    jobs = [
        job
        for job in report.latest_attempt_jobs
        if job.name.startswith(RUNNER_TEST_SHARD_PREFIX)
        and job.start_offset_seconds is not None
        and job.end_offset_seconds is not None
    ]
    if not jobs:
        return None
    return max(job.end_offset_seconds or 0 for job in jobs) - min(job.start_offset_seconds or 0 for job in jobs)


def _elapsed_span_seconds(report: SharedReport) -> float | None:
    starts = [job.start_offset_seconds for job in report.latest_attempt_jobs if job.start_offset_seconds is not None]
    ends = [job.end_offset_seconds for job in report.latest_attempt_jobs if job.end_offset_seconds is not None]
    return max(ends) - min(starts) if starts and ends else None


def _legacy_core_lane_seconds(report: SharedReport) -> float | None:
    candidates = [
        _job_seconds(report, "Build image for tests"),
        _runner_lane_seconds(report),
        _job_seconds(report, "Lint OpenAPI compatibility"),
        _job_seconds(report, "Test migrations · fresh apply"),
        _job_seconds(report, "Lint migration drift · runner"),
    ]
    timed = [value for value in candidates if value is not None]
    return max(timed) if timed else None


def render_legacy_metrics(
    report: SharedReport,
    extension: BackendExtensions,
) -> str:
    backend = extension.backend
    gate_conclusion = next(
        (gate.conclusion for gate in report.required_gates if gate.conclusion),
        "unknown",
    )
    labels = f'test_conclusion="{gate_conclusion}"'
    pytest = backend.pytest
    values: dict[str, float | int | None] = {
        "ci_required_gate_elapsed_seconds": (report.merge_ready_from_run_start_seconds),
        "ci_required_gate_from_run_start_seconds": (report.merge_ready_from_run_start_seconds),
        "ci_required_gate_from_creation_seconds": (report.merge_ready_from_creation_seconds),
        "ci_workflow_initial_queue_seconds": (report.workflow_initial_queue_seconds),
        "ci_elapsed_span_seconds": _elapsed_span_seconds(report),
        "ci_longest_job_seconds": report.longest_latest_job_seconds,
        "ci_raw_runner_seconds": report.runner_cost.raw_runner_seconds,
        "ci_estimated_rounded_runner_minutes": (report.runner_cost.estimated_rounded_runner_minutes),
        "ci_rounding_waste_seconds": (report.runner_cost.rounding_waste_seconds),
        "ci_build_seconds": _job_seconds(report, "Build image for tests"),
        "ci_validate_openapi_seconds": _job_seconds(report, "Lint OpenAPI compatibility"),
        "ci_migration_tier_seconds": _job_seconds(report, "Test migrations · fresh apply"),
        "ci_migration_drift_seconds": _job_seconds(report, "Lint migration drift · runner"),
        "ci_pytest_wall_seconds": (pytest.wall_seconds if pytest else None),
        "ci_coverage_pct": backend.coverage_percent,
    }
    longest_lane = _legacy_core_lane_seconds(report)
    values["ci_critical_path_seconds"] = longest_lane
    values["ci_longest_lane_seconds"] = longest_lane
    lines: list[str] = []
    for metric, value in values.items():
        if value is None:
            continue
        lines.extend(
            (
                f"# TYPE {metric} gauge",
                f"{metric}{{{labels}}} {float(value)}",
            )
        )
    if pytest:
        lines.extend(
            (
                "# TYPE ci_pytest_passed gauge",
                f"ci_pytest_passed{{{labels}}} {pytest.passed}",
                "# TYPE ci_pytest_failed gauge",
                f"ci_pytest_failed{{{labels}}} {pytest.failed}",
            )
        )
    return "\n".join(lines) + "\n"
