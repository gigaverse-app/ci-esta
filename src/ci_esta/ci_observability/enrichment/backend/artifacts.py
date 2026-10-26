"""Parse backend-owned test artifacts and build visible repository signals."""

from __future__ import annotations

from pathlib import Path

from defusedxml import ElementTree as ET
from defusedxml.common import DefusedXmlException

from ci_esta.ci_observability.enrichment.backend.models import (
    BackendEnrichment,
    BackendExtensions,
    GitHubEnrichment,
    JunitTotals,
    PytestSnapshot,
    SlowTest,
)
from ci_esta.ci_observability.enrichment.models import (
    PytestTimingMetadata,
    RepositorySignal,
)
from ci_esta.ci_observability.enrichment.primitives import format_seconds
from ci_esta.ci_observability.models import PYTEST_TIMING_SIGNAL, REPOSITORY_SIGNAL_VALUE_LIMIT


def parse_coverage_xml(path: Path) -> float | None:
    if not path.exists():
        return None
    try:
        root = ET.parse(path).getroot()
        assert root is not None, "Cobertura XML must have a root element"
        rate = root.get("line-rate")
        return round(float(rate) * 100, 1) if rate is not None else None
    except (OSError, ET.ParseError, DefusedXmlException, ValueError):
        return None


def parse_junit_files(paths: list[Path]) -> JunitTotals | None:
    found = False
    slowest: list[SlowTest] = []
    tests = failures = errors = skipped = 0
    total_seconds = 0.0
    for path in paths:
        try:
            root = ET.parse(path).getroot()
            assert root is not None, "JUnit XML must have a root element"
            suites = root.findall("testsuite") or ([root] if root.tag == "testsuite" else [])
            for suite in suites:
                tests += int(suite.get("tests") or 0)
                failures += int(suite.get("failures") or 0)
                errors += int(suite.get("errors") or 0)
                skipped += int(suite.get("skipped") or 0)
                total_seconds += float(suite.get("time") or 0)
            for case in root.findall(".//testcase"):
                seconds = float(case.get("time") or 0)
                classname = case.get("classname") or ""
                name = case.get("name") or "unknown"
                slowest.append(
                    SlowTest(
                        nodeid=f"{classname}::{name}" if classname else name,
                        seconds=seconds,
                    )
                )
        except (OSError, ET.ParseError, DefusedXmlException, ValueError):
            continue
        found = found or bool(suites)
    if not found:
        return None
    return JunitTotals(
        tests=tests,
        failures=failures,
        errors=errors,
        skipped=skipped,
        total_seconds=round(total_seconds, 1),
        slowest=sorted(
            slowest,
            key=lambda item: item.seconds,
            reverse=True,
        )[:5],
    )


def build_extension(
    artifacts_dir: Path,
    github: GitHubEnrichment,
) -> BackendExtensions:
    unavailable = list(github.unavailable)
    metadata_path = artifacts_dir / "ci-pytest-timings.json"
    metadata = None
    if metadata_path.exists():
        try:
            metadata = PytestTimingMetadata.model_validate_json(metadata_path.read_text())
        except (OSError, ValueError) as error:
            unavailable.append(f"pytest timing metadata invalid: {error}")

    junit_paths = sorted(artifacts_dir.glob("report*.xml"))
    junit = parse_junit_files(junit_paths)
    pytest_snapshot = None
    if junit is None:
        unavailable.append("JUnit artifacts unavailable")
    else:
        shard_count = metadata.shard_count if metadata else max(len(junit_paths), 1)
        pytest_snapshot = PytestSnapshot(
            shard_count=shard_count,
            wall_seconds=metadata.wall_seconds if metadata else None,
            total_test_seconds=(metadata.total_test_seconds if metadata else junit.total_seconds),
            passed=max(
                junit.tests - junit.failures - junit.errors - junit.skipped,
                0,
            ),
            failed=junit.failures,
            errors=junit.errors,
            skipped=junit.skipped,
            slowest=junit.slowest,
        )

    return BackendExtensions(
        backend=BackendEnrichment(
            pytest=pytest_snapshot,
            coverage_percent=parse_coverage_xml(artifacts_dir / "coverage.xml"),
            infra_signals=github.infra_signals,
            unavailable=unavailable,
        )
    )


def _summary(value: str) -> str:
    # A display limit must not discard the whole report. Full nodeids and
    # infrastructure labels remain unchanged in the typed extension artifact.
    if len(value) <= REPOSITORY_SIGNAL_VALUE_LIMIT:
        return value
    return value[: REPOSITORY_SIGNAL_VALUE_LIMIT - 1] + "…"


def build_repository_signals(
    extension: BackendExtensions,
) -> list[RepositorySignal]:
    backend = extension.backend
    signals: list[RepositorySignal] = []
    if backend.infra_signals:
        signals.append(
            RepositorySignal(
                key="likely_infra_failure",
                label="⚠️ Likely CI infra failure",
                value=_summary("; ".join(signal.label for signal in backend.infra_signals)),
            )
        )
    if backend.pytest:
        pytest = backend.pytest
        signals.extend(
            (
                RepositorySignal(
                    key="pytest_result",
                    label="pytest",
                    value=(
                        f"{pytest.passed} passed, {pytest.failed} failed, "
                        f"{pytest.errors} errors, {pytest.skipped} skipped"
                    ),
                ),
                RepositorySignal(
                    key=PYTEST_TIMING_SIGNAL,
                    label="pytest timing",
                    value=(
                        f"{pytest.shard_count} shards · "
                        f"{format_seconds(pytest.wall_seconds)} wall · "
                        f"{format_seconds(pytest.total_test_seconds)} summed"
                    ),
                ),
            )
        )
        if pytest.slowest:
            signals.append(
                RepositorySignal(
                    key="slowest_tests",
                    label="Slowest tests",
                    value=_summary("; ".join(f"{test.seconds:.1f}s {test.nodeid}" for test in pytest.slowest[:3])),
                )
            )
    if backend.coverage_percent is not None:
        signals.append(
            RepositorySignal(
                key="line_coverage",
                label="Coverage",
                value=f"{backend.coverage_percent:.1f}% line-rate",
            )
        )
    return signals
