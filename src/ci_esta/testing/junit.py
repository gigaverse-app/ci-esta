"""
Summarize pytest shard timings from JUnit XML artifacts.
"""

from __future__ import annotations

import json
import math
from collections import Counter
from pathlib import Path, PurePosixPath, PureWindowsPath
from tempfile import NamedTemporaryFile

# Element is imported for type annotations only; defusedxml does not re-export
# it, and all parsing below goes through defusedxml. The stdlib class itself
# is inert data, not a parser entry point.
# nosemgrep: python.lang.security.use-defused-xml.use-defused-xml
from xml.etree.ElementTree import Element

import defusedxml.ElementTree as ET
from defusedxml.common import DefusedXmlException
from pydantic import BaseModel, ConfigDict, computed_field

DEFAULT_CANARY_MAX_FILES = 5


class JUnitTimings(BaseModel):
    """
    Aggregate serial work and parallel critical-path time.
    """

    model_config = ConfigDict(frozen=True)

    total_seconds: float
    wall_seconds: float


class PytestFailureCanaryPlan(BaseModel):
    """
    Whole test files selected from terminal failures in prior JUnit reports.
    """

    model_config = ConfigDict(frozen=True)

    selected_files: list[str]
    failing_file_count: int
    terminal_failure_count: int
    truncated: bool
    stale_file_count: int
    invalid_path_count: int
    report_count: int
    valid_report_count: int
    invalid_report_count: int

    @computed_field
    @property
    def selected_file_count(self) -> int:
        return len(self.selected_files)

    @computed_field
    @property
    def has_files(self) -> bool:
        return bool(self.selected_files)


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _parse_junit(path: Path) -> Element | None:
    try:
        return ET.parse(path).getroot()
    except (DefusedXmlException, ET.ParseError, OSError):
        return None


def _safe_relative_test_path(value: str | None) -> str | None:
    if not value:
        return None
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        return None
    normalized = value.replace("\\", "/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    path = PurePosixPath(normalized)
    if (
        normalized.startswith("-")
        or path.is_absolute()
        or PureWindowsPath(normalized).is_absolute()
        or ".." in path.parts
        or path.suffix != ".py"
    ):
        return None
    return path.as_posix()


def _is_current_test_file(file_path: str, working_directory: Path) -> bool:
    """
    Keep prior evidence only when it resolves to a current in-workspace file.
    """
    workspace = working_directory.resolve()
    try:
        candidate = (workspace / file_path).resolve(strict=True)
    except (OSError, RuntimeError):
        return False
    # Enforcement point: prior-run evidence may only name a real file inside
    # the current checkout; stale and escaping paths must fail open.
    return candidate.is_relative_to(workspace) and candidate.is_file()


def _testcase_file_path(testcase: Element, working_directory: Path) -> str | None:
    """
    Resolve a testcase to a safe current file across pytest JUnit families.

    ``xunit1`` reports include ``file``. Pytest's default ``xunit2`` reports do
    not, so progressively trim the dotted classname until it names a current
    Python module (which also handles class-based tests).
    """
    file_path = testcase.get("file")
    if file_path is not None:
        return _safe_relative_test_path(file_path)

    classname = testcase.get("classname")
    if not classname or any(not part.isidentifier() for part in classname.split(".")):
        return None
    parts = classname.split(".")
    # Enforcement point: only a dotted Python identifier that resolves to an
    # existing in-workspace module may become a pytest argument. Trimming is
    # what separates an optional xUnit2 class suffix from the module path.
    for length in range(len(parts), 0, -1):
        candidate = _safe_relative_test_path(f"{'/'.join(parts[:length])}.py")
        if candidate is not None and _is_current_test_file(candidate, working_directory):
            return candidate
    return None


def junit_file_duration(path: Path) -> float | None:
    """
    Return the sum of top-level suite durations in one shard artifact.
    """
    root = _parse_junit(path)
    if root is None:
        return None

    suites = (
        [root]
        if _local_name(root.tag) == "testsuite"
        else [child for child in root if _local_name(child.tag) == "testsuite"]
    )
    durations: list[float] = []
    for suite in suites:
        value = suite.get("time")
        if value is None:
            continue
        try:
            durations.append(float(value))
        except ValueError:
            continue
    return sum(durations) if durations else None


class LearnedTimings(BaseModel):
    """Per-file scheduling hints, never proof of test completeness."""

    model_config = ConfigDict(frozen=True)
    durations: dict[str, float]
    unmapped_cases: int
    skipped_cases: int


def learn_junit_timings(paths: list[Path], working_directory: Path = Path(".")) -> LearnedTimings:
    """Learn file costs from successful, disjoint JUnit reports.

    Unknown files remain absent so the planner applies its unknown-file fallback.
    A partial suite may teach costs for observed files, but cannot prove coverage
    or authorize skipping a test. Keep separate manifests for different lanes.
    """
    if not paths or len({path.resolve() for path in paths}) != len(paths):
        raise ValueError("provide at least one report, without duplicate paths")
    durations: Counter[str] = Counter()
    unmapped = skipped = 0
    for path in paths:
        root = _parse_junit(path)
        if root is None or _local_name(root.tag) not in {"testsuite", "testsuites"}:
            raise ValueError(f"missing or invalid JUnit report: {path}")
        for element in root.iter():
            if _local_name(element.tag) in {"testsuite", "testsuites"}:
                for attribute in ("failures", "errors"):
                    try:
                        count = int(element.get(attribute, "0"))
                    except ValueError as exc:
                        raise ValueError(f"invalid {attribute} count in {path}") from exc
                    if count != 0:
                        raise ValueError(f"unsuccessful JUnit report: {path}")
            if _local_name(element.tag) != "testcase":
                continue
            if any(_local_name(child.tag) in {"failure", "error"} for child in element):
                raise ValueError(f"unsuccessful JUnit report: {path}")
            if any(_local_name(child.tag) == "skipped" for child in element):
                skipped += 1
                continue
            try:
                duration = float(element.attrib["time"])
            except (KeyError, ValueError) as exc:
                raise ValueError(f"missing or invalid testcase duration in {path}") from exc
            if not math.isfinite(duration) or duration < 0:
                raise ValueError(f"non-finite or negative testcase duration in {path}")
            file_path = _testcase_file_path(element, working_directory)
            if file_path is None or not _is_current_test_file(file_path, working_directory):
                unmapped += 1
                continue
            durations[file_path] += duration
    if not durations:
        raise ValueError("no current test files with usable durations")
    return LearnedTimings(durations=dict(sorted(durations.items())), unmapped_cases=unmapped, skipped_cases=skipped)


def write_learned_timings(timings: LearnedTimings, output: Path) -> None:
    """Atomically replace a hint manifest only after every report validates."""
    output.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(mode="w", encoding="utf-8", dir=output.parent, delete=False) as temporary:
        temporary.write(json.dumps(timings.durations, indent=2, allow_nan=False) + "\n")
        temporary_path = Path(temporary.name)
    try:
        temporary_path.replace(output)
    finally:
        temporary_path.unlink(missing_ok=True)


def plan_failure_canary(
    paths: list[Path],
    max_files: int = DEFAULT_CANARY_MAX_FILES,
    working_directory: Path = Path("."),
) -> PytestFailureCanaryPlan:
    """
    Select whole files with prior terminal failures, most failures first.

    A terminal pytest failure is a testcase containing a ``failure`` or
    ``error`` element. Passed and skipped cases do not enter the canary.
    """
    if max_files < 1:
        raise ValueError("max_files must be at least 1")

    failure_counts: Counter[str] = Counter()
    terminal_failure_count = 0
    invalid_path_count = 0
    valid_report_count = 0
    for report_path in paths:
        root = _parse_junit(report_path)
        if root is None or _local_name(root.tag) not in {"testsuite", "testsuites"}:
            continue
        valid_report_count += 1
        for testcase in root.iter():
            if _local_name(testcase.tag) != "testcase":
                continue
            terminal = any(_local_name(child.tag) in {"failure", "error"} for child in testcase)
            if not terminal:
                continue
            terminal_failure_count += 1
            file_path = _testcase_file_path(testcase, working_directory)
            if file_path is None:
                invalid_path_count += 1
                continue
            failure_counts[file_path] += 1

    stale_files = {file_path for file_path in failure_counts if not _is_current_test_file(file_path, working_directory)}
    runnable_counts = {file_path: count for file_path, count in failure_counts.items() if file_path not in stale_files}
    ordered_files = sorted(runnable_counts, key=lambda file_path: (-runnable_counts[file_path], file_path))
    return PytestFailureCanaryPlan(
        selected_files=ordered_files[:max_files],
        failing_file_count=len(failure_counts),
        terminal_failure_count=terminal_failure_count,
        truncated=len(ordered_files) > max_files,
        stale_file_count=len(stale_files),
        invalid_path_count=invalid_path_count,
        report_count=len(paths),
        valid_report_count=valid_report_count,
        invalid_report_count=len(paths) - valid_report_count,
    )


def write_pytest_paths_file(paths: list[str], output: Path) -> None:
    """
    Write pytest paths as a newline-delimited file, empty when there are none.
    """
    output.parent.mkdir(parents=True, exist_ok=True)
    content = "\n".join(paths)
    output.write_text(f"{content}\n" if content else "")


def write_failure_canary_file(plan: PytestFailureCanaryPlan, output: Path) -> None:
    """
    Write selected files as newline-delimited pytest arguments.
    """
    write_pytest_paths_file(plan.selected_files, output)


def format_failure_canary_summary(
    plan: PytestFailureCanaryPlan,
    expected_report_count: int | None = None,
) -> str:
    """
    Format stable planner diagnostics for CLI and composite-action logs.
    """
    report_counts = f"{plan.valid_report_count}/{plan.report_count}"
    if expected_report_count is not None:
        report_counts = f"{report_counts}/{expected_report_count}"
    return (
        f"selected_files={plan.selected_file_count} failing_files={plan.failing_file_count} "
        f"terminal_failures={plan.terminal_failure_count} truncated={str(plan.truncated).lower()} "
        f"reports={report_counts} stale_files={plan.stale_file_count} "
        f"invalid_paths={plan.invalid_path_count}"
    )


def summarize_junit_timings(paths: list[Path]) -> JUnitTimings:
    """
    Return total test time and slowest-shard wall time.
    """
    shard_durations = [duration for path in paths if (duration := junit_file_duration(path)) is not None]
    return JUnitTimings(total_seconds=sum(shard_durations), wall_seconds=max(shard_durations, default=0.0))


def format_duration(seconds: float) -> str:
    """
    Format seconds for a concise CI summary.
    """
    minutes, secs = divmod(int(seconds), 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}h {minutes}m {secs}s"
    if minutes:
        return f"{minutes}m {secs}s"
    return f"{secs}s"
