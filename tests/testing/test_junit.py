from pathlib import Path

import pytest

from ci_esta.testing.junit import (
    DEFAULT_CANARY_MAX_FILES,
    format_duration,
    plan_failure_canary,
    summarize_junit_timings,
)


def _write_junit(tmp_path: Path, name: str, testcases: str) -> Path:
    report = tmp_path / name
    report.write_text(f'<testsuite name="pytest">{testcases}</testsuite>')
    return report


def _touch_test_files(root: Path, *paths: str) -> None:
    for value in paths:
        path = root / value
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()


def test_summarizes_total_and_slowest_shard_time(tmp_path: Path) -> None:
    first = tmp_path / "first.xml"
    first.write_text('<testsuites><testsuite name="a" time="40.25"/><testsuite name="b" time="10.25"/></testsuites>')
    second = tmp_path / "second.xml"
    second.write_text('<testsuite name="pytest" time="70.0"/>')

    timings = summarize_junit_timings([first, second])

    assert timings.total_seconds == pytest.approx(120.5)
    assert timings.wall_seconds == pytest.approx(70.0)


def test_ignores_malformed_and_entity_bearing_xml(tmp_path: Path) -> None:
    malformed = tmp_path / "malformed.xml"
    malformed.write_text("<testsuites>")
    unsafe = tmp_path / "unsafe.xml"
    unsafe.write_text('<!DOCTYPE testsuite [<!ENTITY duration "12.4">]><testsuite time="&duration;"/>')

    timings = summarize_junit_timings([malformed, unsafe])

    assert timings.total_seconds == 0.0
    assert timings.wall_seconds == 0.0


def test_ignores_suites_without_a_numeric_duration(tmp_path: Path) -> None:
    report = tmp_path / "invalid-durations.xml"
    report.write_text('<testsuites><testsuite name="missing"/><testsuite name="invalid" time="slow"/></testsuites>')

    timings = summarize_junit_timings([report])

    assert timings.total_seconds == 0.0
    assert timings.wall_seconds == 0.0


def test_failure_canary_selects_whole_files_with_terminal_failures(tmp_path: Path) -> None:
    _touch_test_files(tmp_path, "tests/test_first.py", "tests/test_second.py")
    report = _write_junit(
        tmp_path,
        "report.xml",
        """
        <testcase file="tests/test_first.py" name="test_passes" />
        <testcase file="tests/test_first.py" name="test_fails"><failure /></testcase>
        <testcase file="tests/test_first.py" name="test_was_not_the_failure" />
        <testcase file="tests/test_second.py" name="test_errors"><error /></testcase>
        <testcase file="tests/test_skipped.py" name="test_skipped"><skipped /></testcase>
        """,
    )

    plan = plan_failure_canary([report], working_directory=tmp_path)

    assert plan.selected_files == ["tests/test_first.py", "tests/test_second.py"]
    assert plan.failing_file_count == 2
    assert plan.terminal_failure_count == 2
    assert plan.truncated is False


def test_failure_canary_deduplicates_and_ranks_files_by_failure_count(tmp_path: Path) -> None:
    _touch_test_files(tmp_path, "tests/test_one.py", "tests/test_two.py", "tests/test_three.py")
    first = _write_junit(
        tmp_path,
        "first.xml",
        """
        <testcase file="tests/test_one.py" name="test_a"><failure /></testcase>
        <testcase file="tests/test_two.py" name="test_b"><failure /></testcase>
        """,
    )
    second = _write_junit(
        tmp_path,
        "second.xml",
        """
        <testcase file="tests/test_two.py" name="test_c"><error /></testcase>
        <testcase file="./tests/test_three.py" name="test_d"><failure /></testcase>
        """,
    )

    plan = plan_failure_canary([first, second], max_files=2, working_directory=tmp_path)

    assert plan.selected_files == ["tests/test_two.py", "tests/test_one.py"]
    assert plan.failing_file_count == 3
    assert plan.terminal_failure_count == 4
    assert plan.truncated is True


def test_failure_canary_uses_bounded_default_and_ignores_unusable_paths(tmp_path: Path) -> None:
    _touch_test_files(
        tmp_path,
        *(f"tests/test_{index}.py" for index in range(DEFAULT_CANARY_MAX_FILES + 2)),
    )
    cases = "".join(
        f'<testcase file="tests/test_{index}.py" name="test_failure"><failure /></testcase>'
        for index in range(DEFAULT_CANARY_MAX_FILES + 2)
    )
    cases += '<testcase name="test_without_file"><failure /></testcase>'
    cases += '<testcase file="../outside.py" name="test_unsafe"><failure /></testcase>'
    cases += '<testcase file="/tmp/test_absolute.py" name="test_absolute"><failure /></testcase>'
    cases += '<testcase file="C:\\tmp\\test_windows.py" name="test_windows"><failure /></testcase>'
    report = _write_junit(tmp_path, "report.xml", cases)

    plan = plan_failure_canary([report], working_directory=tmp_path)

    assert len(plan.selected_files) == DEFAULT_CANARY_MAX_FILES
    assert plan.failing_file_count == DEFAULT_CANARY_MAX_FILES + 2
    assert plan.truncated is True


def test_failure_canary_ignores_invalid_reports_and_rejects_invalid_limit(tmp_path: Path) -> None:
    malformed = tmp_path / "malformed.xml"
    malformed.write_text("<testsuite>")
    unsafe = tmp_path / "unsafe.xml"
    unsafe.write_text('<!DOCTYPE testsuite [<!ENTITY path "tests/test_bad.py">]><testcase file="&path;"/>')

    assert plan_failure_canary([malformed, unsafe]).selected_files == []
    with pytest.raises(ValueError, match="max_files must be at least 1"):
        plan_failure_canary([], max_files=0)


def test_failure_canary_drops_files_missing_from_the_current_checkout(tmp_path: Path) -> None:
    report = _write_junit(
        tmp_path,
        "report.xml",
        '<testcase file="tests/test_deleted.py" name="test_failure"><failure /></testcase>',
    )

    plan = plan_failure_canary([report], working_directory=tmp_path)

    assert plan.selected_files == []
    assert plan.failing_file_count == 1
    assert plan.stale_file_count == 1


@pytest.mark.parametrize(
    ("classname", "expected_file"),
    (
        (
            "deployment.scripts.tests.test_ci_observability",
            "deployment/scripts/tests/test_ci_observability.py",
        ),
        (
            "deployment.scripts.tests.test_ci_observability.TestReporter",
            "deployment/scripts/tests/test_ci_observability.py",
        ),
        ("deployment.scripts.tests.test_missing.TestReporter", None),
        ("deployment.scripts.tests.test_ci_observability.Test-Reporter", None),
    ),
    ids=("module", "class-suffix", "missing-module", "invalid-identifier"),
)
def test_failure_canary_resolves_only_current_xunit2_modules(
    tmp_path: Path,
    classname: str,
    expected_file: str | None,
) -> None:
    """
    INVARIANT: xUnit2 evidence selects only a current in-workspace module.
    """
    _touch_test_files(tmp_path, "deployment/scripts/tests/test_ci_observability.py")
    report = _write_junit(
        tmp_path,
        "report.xml",
        f'<testcase classname="{classname}" name="test_failure"><failure /></testcase>',
    )

    plan = plan_failure_canary([report], working_directory=tmp_path)

    assert plan.selected_files == ([expected_file] if expected_file is not None else [])
    assert plan.invalid_path_count == (0 if expected_file is not None else 1)


def test_failure_canary_drops_symlinks_that_escape_the_current_checkout(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    tests_dir = workspace / "tests"
    tests_dir.mkdir(parents=True)
    outside = tmp_path / "test_outside.py"
    outside.touch()
    (tests_dir / "test_link.py").symlink_to(outside)
    report = _write_junit(
        tmp_path,
        "report.xml",
        '<testcase file="tests/test_link.py" name="test_failure"><failure /></testcase>',
    )

    plan = plan_failure_canary([report], working_directory=workspace)

    assert plan.selected_files == []
    assert plan.stale_file_count == 1


def test_failure_canary_treats_symlink_loops_as_stale_evidence(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    tests_dir = workspace / "tests"
    tests_dir.mkdir(parents=True)
    loop = tests_dir / "test_loop.py"
    loop.symlink_to(loop)
    report = _write_junit(
        tmp_path,
        "report.xml",
        '<testcase file="tests/test_loop.py" name="test_failure"><failure /></testcase>',
    )

    plan = plan_failure_canary([report], working_directory=workspace)

    assert plan.selected_files == []
    assert plan.stale_file_count == 1


@pytest.mark.parametrize(
    ("unsafe_path_xml", "unsafe_path"),
    [
        ("--collect-only.py", "--collect-only.py"),
        ("tests/test_ok.py&#10;--collect-only.py", "tests/test_ok.py\n--collect-only.py"),
        ("tests/test_ok.py&#13;--co.py", "tests/test_ok.py\r--co.py"),
    ],
)
def test_failure_canary_rejects_paths_that_can_change_pytest_arguments(
    tmp_path: Path,
    unsafe_path_xml: str,
    unsafe_path: str,
) -> None:
    _touch_test_files(tmp_path, unsafe_path)
    report = _write_junit(
        tmp_path,
        "report.xml",
        f'<testcase file="{unsafe_path_xml}" name="test_failure"><failure /></testcase>',
    )

    plan = plan_failure_canary([report], working_directory=tmp_path)

    assert plan.selected_files == []
    assert plan.invalid_path_count == 1


@pytest.mark.parametrize(
    ("seconds", "expected"),
    [(9.4, "9s"), (59.6, "59s"), (568.9, "9m 28s"), (3723.9, "1h 2m 3s")],
)
def test_formats_human_readable_duration(seconds: float, expected: str) -> None:
    assert format_duration(seconds) == expected
