"""
Run a planned pytest failure canary without letting un-runnable files brick the retry lane.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from collections.abc import Callable
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, ConfigDict, computed_field

from ci_esta.testing.junit import write_pytest_paths_file

PYTEST_EXIT_NO_TESTS_COLLECTED = 5
PYTEST_EXIT_USAGE_ERROR = 4
DEFAULT_COLLECT_TIMEOUT_SECONDS = 120.0
# Bounds total staging time so a paths file full of hanging files cannot push
# the canary job into its own timeout-minutes kill (failure, not fall-through).
DEFAULT_STAGE_BUDGET_SECONDS = 180.0
# The planner caps its output at DEFAULT_CANARY_MAX_FILES; a paths file far
# beyond that is corrupt input, not a plan, and is not worth probing at all.
MAX_STAGED_FILES = 25
PROBE_DETAIL_MAX_CHARS = 2000


class CanaryProbeOutcome(StrEnum):
    RUNNABLE = "runnable"
    DESELECTED = "deselected"
    UNCOLLECTABLE = "uncollectable"
    TIMED_OUT = "timed-out"
    BUDGET_EXHAUSTED = "budget-exhausted"


class CanaryFileProbe(BaseModel):
    """
    Collectability verdict for one planned prior-failure file.
    """

    model_config = ConfigDict(frozen=True)

    file: str
    outcome: CanaryProbeOutcome
    detail: str = ""


class CanaryRunPlan(BaseModel):
    """
    Planned files partitioned into runnable survivors and dropped evidence.
    """

    model_config = ConfigDict(frozen=True)

    probes: list[CanaryFileProbe]

    @computed_field
    @property
    def runnable_files(self) -> list[str]:
        return [probe.file for probe in self.probes if probe.outcome is CanaryProbeOutcome.RUNNABLE]

    @computed_field
    @property
    def dropped(self) -> list[CanaryFileProbe]:
        return [probe for probe in self.probes if probe.outcome is not CanaryProbeOutcome.RUNNABLE]


def _tail(text: str) -> str:
    return text[-PROBE_DETAIL_MAX_CHARS:]


def _pytest_command(*args: str) -> list[str]:
    # The prior-failure file plan is authoritative. Native local selection must
    # not turn an unchanged, still-failing canary into a successful empty run.
    # Explicit loading also supports consumers that disable plugin autoload.
    return [sys.executable, "-m", "pytest", "-p", "selective", "--no-selective", *args]


def probe_collection(
    file: str,
    pytest_args: list[str],
    timeout_seconds: float = DEFAULT_COLLECT_TIMEOUT_SECONDS,
) -> CanaryFileProbe:
    """
    Check with the exact run arguments whether pytest can still collect a file.
    """
    command = _pytest_command("--collect-only", "-q", *pytest_args, "--", file)
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired:
        return CanaryFileProbe(
            file=file,
            outcome=CanaryProbeOutcome.TIMED_OUT,
            detail=f"collection did not finish within {timeout_seconds}s",
        )
    if completed.returncode == 0:
        return CanaryFileProbe(file=file, outcome=CanaryProbeOutcome.RUNNABLE)
    if completed.returncode == PYTEST_EXIT_NO_TESTS_COLLECTED:
        return CanaryFileProbe(
            file=file,
            outcome=CanaryProbeOutcome.DESELECTED,
            detail=_tail(completed.stdout),
        )
    return CanaryFileProbe(
        file=file,
        outcome=CanaryProbeOutcome.UNCOLLECTABLE,
        detail=_tail(f"{completed.stdout}\n{completed.stderr}"),
    )


def _probe_all_files_together(
    files: list[str],
    pytest_args: list[str],
    timeout_seconds: float,
) -> CanaryRunPlan | None:
    """
    Try one combined collection over all files; None means isolate per file.

    A single pytest startup covers the common cases — every file collects (exit 0) or every file deselects (exit 5) — so
    the expensive per-file probes only run when the combined result cannot attribute a failure.
    """
    command = _pytest_command("--collect-only", "-q", *pytest_args, "--", *files)
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired:
        return None
    if completed.returncode == 0:
        return CanaryRunPlan(probes=[CanaryFileProbe(file=file, outcome=CanaryProbeOutcome.RUNNABLE) for file in files])
    if completed.returncode == PYTEST_EXIT_NO_TESTS_COLLECTED:
        detail = _tail(completed.stdout)
        return CanaryRunPlan(
            probes=[CanaryFileProbe(file=file, outcome=CanaryProbeOutcome.DESELECTED, detail=detail) for file in files]
        )
    return None


def stage_canary_files(
    files: list[str],
    prober: Callable[[str], CanaryFileProbe],
    budget_seconds: float | None = None,
    monotonic: Callable[[], float] = time.monotonic,
) -> CanaryRunPlan:
    """
    Probe planned files within a time budget and partition into runnable and dropped.

    Files not reached before the budget expires are dropped (fall-through), never left to push the surrounding CI job
    into its own timeout.
    """
    start = monotonic()
    probes: list[CanaryFileProbe] = []
    for file in files:
        if budget_seconds is not None and monotonic() - start >= budget_seconds:
            probes.append(
                CanaryFileProbe(
                    file=file,
                    outcome=CanaryProbeOutcome.BUDGET_EXHAUSTED,
                    detail=f"staging budget of {budget_seconds}s exhausted before this file was probed",
                )
            )
            continue
        probes.append(prober(file))
    return CanaryRunPlan(probes=probes)


def _read_canary_files(canary_file: Path) -> list[str] | None:
    if not canary_file.is_file():
        print(f"canary-run: canary file {canary_file} does not exist", file=sys.stderr)
        return None
    return [line.strip() for line in canary_file.read_text().splitlines() if line.strip()]


def _append_github_outputs(plan: CanaryRunPlan) -> None:
    output_path = os.environ.get("GITHUB_OUTPUT")
    if not output_path:
        return
    with Path(output_path).open("a") as output:
        output.write(f"has_files={str(bool(plan.runnable_files)).lower()}\n")
        output.write(f"staged_count={len(plan.probes)}\n")
        output.write(f"runnable_count={len(plan.runnable_files)}\n")
        output.write(f"dropped_count={len(plan.dropped)}\n")


def _stage_and_report(
    files: list[str],
    pytest_args: list[str],
    collect_timeout_seconds: float,
    stage_budget_seconds: float,
    prober: Callable[[str], CanaryFileProbe] | None,
) -> CanaryRunPlan:
    start = time.monotonic()
    plan: CanaryRunPlan | None = None
    if prober is None:
        plan = _probe_all_files_together(
            files, pytest_args, timeout_seconds=min(collect_timeout_seconds, stage_budget_seconds)
        )
        prober = lambda file: probe_collection(file, pytest_args, timeout_seconds=collect_timeout_seconds)  # noqa: E731
    if plan is None:
        remaining_budget = max(0.0, stage_budget_seconds - (time.monotonic() - start))
        plan = stage_canary_files(files, prober, budget_seconds=remaining_budget)
    for probe in plan.dropped:
        print(
            f"canary-run: dropping {probe.file}: {probe.outcome} — "
            "no longer retryable here; the full matrix will re-establish evidence"
        )
        if probe.detail:
            print(probe.detail)
    print(f"canary-run: staged={len(plan.probes)} runnable={len(plan.runnable_files)} dropped={len(plan.dropped)}")
    _append_github_outputs(plan)
    return plan


def _read_sane_canary_files(canary_file: Path) -> list[str] | int:
    """
    Read the paths file, returning an exit code when staging must not proceed.
    """
    files = _read_canary_files(canary_file)
    if files is None:
        return PYTEST_EXIT_USAGE_ERROR
    if len(files) > MAX_STAGED_FILES:
        print(
            f"canary-run: {len(files)} planned files exceeds the sanity cap of {MAX_STAGED_FILES}; "
            "treating the paths file as corrupt and falling through to the full matrix"
        )
        _append_github_outputs(CanaryRunPlan(probes=[]))
        return 0
    if not files:
        print("canary-run: no prior-failure files planned; falling through to the full matrix")
        _append_github_outputs(CanaryRunPlan(probes=[]))
        return 0
    return files


def run_canary(
    canary_file: Path,
    pytest_args: list[str],
    collect_timeout_seconds: float = DEFAULT_COLLECT_TIMEOUT_SECONDS,
    stage_budget_seconds: float = DEFAULT_STAGE_BUDGET_SECONDS,
    prober: Callable[[str], CanaryFileProbe] | None = None,
) -> int:
    """
    Run runnable prior-failure files; fall through to the matrix otherwise.

    Enforcement point: the canary is a staging optimization, so it may only
    fail on evidence the authoritative full matrix would reproduce. Any file
    that can no longer be collected, is fully deselected, hangs at collection,
    or is not probed within the staging budget is dropped, and an empty
    survivor set exits 0 so the matrix runs and refreshes the pytest-red PR
    state instead of deadlocking.
    """
    files = _read_sane_canary_files(canary_file)
    if isinstance(files, int):
        return files
    plan = _stage_and_report(files, pytest_args, collect_timeout_seconds, stage_budget_seconds, prober)
    if not plan.runnable_files:
        print("canary-run: no runnable prior-failure files remain; falling through to the full matrix")
        return 0
    completed = subprocess.run(_pytest_command(*pytest_args, "--", *plan.runnable_files))
    if completed.returncode == PYTEST_EXIT_NO_TESTS_COLLECTED:
        print("canary-run: pytest collected no tests from staged files; falling through to the full matrix")
        return 0
    return completed.returncode


def prune_canary(
    canary_file: Path,
    pytest_args: list[str],
    collect_timeout_seconds: float = DEFAULT_COLLECT_TIMEOUT_SECONDS,
    stage_budget_seconds: float = DEFAULT_STAGE_BUDGET_SECONDS,
    output: Path | None = None,
    prober: Callable[[str], CanaryFileProbe] | None = None,
) -> int:
    """
    Rewrite the paths file to runnable survivors for consumer-owned runners.
    """
    files = _read_sane_canary_files(canary_file)
    if isinstance(files, int):
        if files == 0:
            write_pytest_paths_file([], output or canary_file)
        return files
    plan = _stage_and_report(files, pytest_args, collect_timeout_seconds, stage_budget_seconds, prober)
    write_pytest_paths_file(plan.runnable_files, output or canary_file)
    return 0
