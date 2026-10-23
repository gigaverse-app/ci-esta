import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest

from ci_esta.testing.canary_run import (
    MAX_STAGED_FILES,
    PYTEST_EXIT_NO_TESTS_COLLECTED,
    PYTEST_EXIT_USAGE_ERROR,
    CanaryFileProbe,
    CanaryProbeOutcome,
    prune_canary,
    run_canary,
    stage_canary_files,
)
from tests.testing.git_repo import commit, write

DESELECT_QUARANTINE_ARGS = ["-m", "not quarantine", "-p", "no:cacheprovider"]
SHORT_COLLECT_TIMEOUT_SECONDS = 8.0
GENEROUS_STAGE_BUDGET_SECONDS = 120.0
HANGING_IMPORT_SLEEP_SECONDS = 30
TINY_COLLECT_TIMEOUT_SECONDS = 1.0
TINY_STAGE_BUDGET_SECONDS = 1.5

BROKEN_IMPORT_FILE = "tests/test_broken_import.py"
QUARANTINED_FILE = "tests/test_quarantined.py"
PASSING_FILE = "tests/test_passing.py"
FAILING_FILE = "tests/test_failing.py"

TEST_SOURCES = {
    BROKEN_IMPORT_FILE: "import module_that_does_not_exist_anywhere\n\ndef test_never_collected():\n    assert True\n",
    QUARANTINED_FILE: ("import pytest\n\n@pytest.mark.quarantine\ndef test_quarantined():\n    assert True\n"),
    PASSING_FILE: "def test_passes():\n    assert True\n",
    FAILING_FILE: "def test_fails():\n    assert False\n",
}


def _write_project(tmp_path: Path, canary_entries: list[str]) -> Path:
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir(exist_ok=True)
    for file_path in canary_entries:
        (tmp_path / file_path).write_text(TEST_SOURCES[file_path])
    canary_file = tmp_path / "pytest-failure-canary.txt"
    canary_file.write_text("".join(f"{entry}\n" for entry in canary_entries))
    return canary_file


def test_uncollectable_and_deselected_files_fall_through_to_the_full_matrix(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """
    INVARIANT: the canary may only fail for evidence the full matrix would
    reproduce; a quarantined or un-importable prior-failure file must never
    brick the retry lane (the gigaverse-ai update-backend-common-pr147 deadlock).
    """
    monkeypatch.chdir(tmp_path)
    canary_file = _write_project(tmp_path, [BROKEN_IMPORT_FILE, QUARANTINED_FILE])

    result = run_canary(
        canary_file,
        DESELECT_QUARANTINE_ARGS,
        collect_timeout_seconds=SHORT_COLLECT_TIMEOUT_SECONDS,
    )

    assert result == 0
    output = capsys.readouterr().out
    assert f"dropping {BROKEN_IMPORT_FILE}" in output
    assert f"dropping {QUARANTINED_FILE}" in output
    assert "falling through to the full matrix" in output


def test_runnable_prior_failure_still_fails_the_canary(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """
    INVARIANT: tolerating un-runnable files must not weaken the gate for
    failures that are still real and runnable.
    """
    monkeypatch.chdir(tmp_path)
    canary_file = _write_project(tmp_path, [FAILING_FILE])

    result = run_canary(
        canary_file,
        DESELECT_QUARANTINE_ARGS,
        collect_timeout_seconds=SHORT_COLLECT_TIMEOUT_SECONDS,
    )

    assert result == 1


@pytest.mark.parametrize("autoload", [True, False])
def test_planned_canary_does_not_reselect_unchanged_failures(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, autoload: bool
) -> None:
    """A saved failure plan remains authoritative even with local selective defaults."""
    monkeypatch.chdir(tmp_path)
    if autoload:
        monkeypatch.delenv("PYTEST_DISABLE_PLUGIN_AUTOLOAD", raising=False)
    else:
        monkeypatch.setenv("PYTEST_DISABLE_PLUGIN_AUTOLOAD", "1")
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    canary_file = _write_project(tmp_path, [FAILING_FILE])
    write(tmp_path, "pytest.ini", "[pytest]\nselective = true\n")
    write(tmp_path, ".gitignore", "__pycache__/\n.pytest_cache/\n")
    commit(tmp_path)
    # Explicit activation also covers a caller forwarding --selective by mistake.
    assert run_canary(canary_file, ["-p", "selective", "--selective", "-q"]) == 1


def test_mixed_canary_drops_unrunnable_files_and_runs_the_rest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(tmp_path)
    canary_file = _write_project(tmp_path, [BROKEN_IMPORT_FILE, QUARANTINED_FILE, PASSING_FILE])

    result = run_canary(
        canary_file,
        DESELECT_QUARANTINE_ARGS,
        collect_timeout_seconds=SHORT_COLLECT_TIMEOUT_SECONDS,
    )

    assert result == 0
    output = capsys.readouterr().out
    assert "staged=3 runnable=1 dropped=2" in output


def test_empty_canary_file_falls_through_without_running_pytest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(tmp_path)
    canary_file = tmp_path / "pytest-failure-canary.txt"
    canary_file.write_text("")

    result = run_canary(canary_file, [], collect_timeout_seconds=SHORT_COLLECT_TIMEOUT_SECONDS)

    assert result == 0
    assert "falling through to the full matrix" in capsys.readouterr().out


@pytest.mark.parametrize("entrypoint", [run_canary, prune_canary], ids=["run", "prune"])
def test_missing_canary_file_is_a_loud_usage_error(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    entrypoint: Callable[..., int],
) -> None:
    result = entrypoint(
        tmp_path / "does-not-exist.txt",
        [],
        collect_timeout_seconds=SHORT_COLLECT_TIMEOUT_SECONDS,
    )

    assert result == PYTEST_EXIT_USAGE_ERROR
    assert "does-not-exist.txt" in capsys.readouterr().err


def test_hanging_collection_is_dropped_instead_of_hanging_the_lane(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(tmp_path)
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    hanging_file = "tests/test_hanging_import.py"
    (tmp_path / hanging_file).write_text(
        f"import time\ntime.sleep({HANGING_IMPORT_SLEEP_SECONDS})\n\ndef test_never_reached():\n    assert True\n"
    )
    canary_file = tmp_path / "pytest-failure-canary.txt"
    canary_file.write_text(f"{hanging_file}\n")

    result = run_canary(canary_file, [], collect_timeout_seconds=TINY_COLLECT_TIMEOUT_SECONDS)

    assert result == 0
    output = capsys.readouterr().out
    assert f"dropping {hanging_file}" in output
    assert "timed-out" in output


@pytest.mark.parametrize("in_place", [True, False], ids=["in-place", "separate-output"])
def test_prune_only_rewrites_the_paths_file_with_runnable_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, in_place: bool
) -> None:
    monkeypatch.chdir(tmp_path)
    canary_file = _write_project(tmp_path, [BROKEN_IMPORT_FILE, PASSING_FILE])
    output = canary_file if in_place else tmp_path / "pruned.txt"

    result = prune_canary(
        canary_file,
        DESELECT_QUARANTINE_ARGS,
        collect_timeout_seconds=SHORT_COLLECT_TIMEOUT_SECONDS,
        output=None if in_place else output,
    )

    assert result == 0
    assert output.read_text() == f"{PASSING_FILE}\n"


def test_prune_only_writes_an_empty_file_when_nothing_survives(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    canary_file = _write_project(tmp_path, [BROKEN_IMPORT_FILE])

    result = prune_canary(
        canary_file,
        DESELECT_QUARANTINE_ARGS,
        collect_timeout_seconds=SHORT_COLLECT_TIMEOUT_SECONDS,
    )

    assert result == 0
    assert canary_file.read_text() == ""


def _probe_with_outcome(outcome: CanaryProbeOutcome) -> CanaryFileProbe:
    return CanaryFileProbe(file="tests/test_any.py", outcome=outcome, detail="probe detail")


@pytest.mark.parametrize(
    ("outcome", "runnable"),
    [
        (CanaryProbeOutcome.RUNNABLE, True),
        (CanaryProbeOutcome.DESELECTED, False),
        (CanaryProbeOutcome.UNCOLLECTABLE, False),
        (CanaryProbeOutcome.TIMED_OUT, False),
    ],
)
def test_stage_classifies_files_by_probe_outcome(outcome: CanaryProbeOutcome, runnable: bool) -> None:
    plan = stage_canary_files(["tests/test_any.py"], lambda _: _probe_with_outcome(outcome))

    assert (plan.runnable_files == ["tests/test_any.py"]) is runnable
    assert (len(plan.dropped) == 1) is not runnable


def test_run_where_staged_files_collect_no_tests_falls_through(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """
    Belt-and-braces: even if a probe admits a file whose tests all deselect in
    the combined run, "no tests collected" is fall-through, not failure.
    """
    monkeypatch.chdir(tmp_path)
    canary_file = _write_project(tmp_path, [QUARANTINED_FILE])

    def _always_runnable(file: str) -> CanaryFileProbe:
        return CanaryFileProbe(file=file, outcome=CanaryProbeOutcome.RUNNABLE)

    result = run_canary(
        canary_file,
        DESELECT_QUARANTINE_ARGS,
        collect_timeout_seconds=SHORT_COLLECT_TIMEOUT_SECONDS,
        prober=_always_runnable,
    )

    assert result == 0
    assert "collected no tests" in capsys.readouterr().out


def test_pytest_no_tests_collected_constant_matches_pytest() -> None:
    assert PYTEST_EXIT_NO_TESTS_COLLECTED == pytest.ExitCode.NO_TESTS_COLLECTED
    assert PYTEST_EXIT_USAGE_ERROR == pytest.ExitCode.USAGE_ERROR


def _write_hanging_project(tmp_path: Path, file_names: list[str]) -> Path:
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir(exist_ok=True)
    for file_name in file_names:
        (tmp_path / file_name).write_text(
            f"import time\ntime.sleep({HANGING_IMPORT_SLEEP_SECONDS})\n\ndef test_never_reached():\n    assert True\n"
        )
    canary_file = tmp_path / "pytest-failure-canary.txt"
    canary_file.write_text("".join(f"{entry}\n" for entry in file_names))
    return canary_file


def test_staging_budget_bounds_total_probe_time_and_falls_through(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """
    INVARIANT: total staging time is bounded by the stage budget, so a paths
    file full of hanging files cannot push the canary job into its own
    timeout-minutes kill (which would read as failure instead of fall-through).
    """
    monkeypatch.chdir(tmp_path)
    canary_file = _write_hanging_project(
        tmp_path, ["tests/test_hang_one.py", "tests/test_hang_two.py", "tests/test_hang_three.py"]
    )

    result = run_canary(
        canary_file,
        [],
        collect_timeout_seconds=TINY_COLLECT_TIMEOUT_SECONDS,
        stage_budget_seconds=TINY_STAGE_BUDGET_SECONDS,
    )

    assert result == 0
    output = capsys.readouterr().out
    assert "budget-exhausted" in output
    assert "falling through to the full matrix" in output


def test_stage_stops_probing_once_budget_is_exhausted() -> None:
    probed: list[str] = []
    clock_readings = iter([0.0, 0.0, 10.0])

    def _probe(file: str) -> CanaryFileProbe:
        probed.append(file)
        return CanaryFileProbe(file=file, outcome=CanaryProbeOutcome.RUNNABLE)

    plan = stage_canary_files(
        ["tests/test_first.py", "tests/test_second.py"],
        _probe,
        budget_seconds=5.0,
        monotonic=lambda: next(clock_readings),
    )

    assert probed == ["tests/test_first.py"]
    assert plan.probes[1].outcome is CanaryProbeOutcome.BUDGET_EXHAUSTED


def test_oversized_paths_file_is_treated_as_corrupt_and_falls_through(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    canary_file = tmp_path / "pytest-failure-canary.txt"
    canary_file.write_text("".join(f"tests/test_{index}.py\n" for index in range(MAX_STAGED_FILES + 1)))

    result = run_canary(canary_file, [], collect_timeout_seconds=TINY_COLLECT_TIMEOUT_SECONDS)

    assert result == 0
    assert "falling through to the full matrix" in capsys.readouterr().out


def test_oversized_paths_file_prunes_to_empty(tmp_path: Path) -> None:
    canary_file = tmp_path / "pytest-failure-canary.txt"
    canary_file.write_text("".join(f"tests/test_{index}.py\n" for index in range(MAX_STAGED_FILES + 1)))

    result = prune_canary(canary_file, [], collect_timeout_seconds=TINY_COLLECT_TIMEOUT_SECONDS)

    assert result == 0
    assert canary_file.read_text() == ""


def test_all_deselected_files_drop_via_the_combined_probe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(tmp_path)
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    for file_name in ("tests/test_quarantined_one.py", "tests/test_quarantined_two.py"):
        (tmp_path / file_name).write_text(TEST_SOURCES[QUARANTINED_FILE])
    canary_file = tmp_path / "pytest-failure-canary.txt"
    canary_file.write_text("tests/test_quarantined_one.py\ntests/test_quarantined_two.py\n")

    result = run_canary(
        canary_file,
        DESELECT_QUARANTINE_ARGS,
        collect_timeout_seconds=SHORT_COLLECT_TIMEOUT_SECONDS,
    )

    assert result == 0
    output = capsys.readouterr().out
    assert "staged=2 runnable=0 dropped=2" in output
    assert "deselected" in output


def test_github_outputs_expose_staging_results_for_workflow_gating(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    INVARIANT: a workflow can gate its own pytest step on has_files instead of
    re-parsing the pruned paths file (an empty file fed to a bare pytest call
    would run the entire suite).
    """
    monkeypatch.chdir(tmp_path)
    canary_file = _write_project(tmp_path, [BROKEN_IMPORT_FILE, PASSING_FILE])
    github_output = tmp_path / "github-output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(github_output))

    result = prune_canary(
        canary_file,
        DESELECT_QUARANTINE_ARGS,
        collect_timeout_seconds=SHORT_COLLECT_TIMEOUT_SECONDS,
    )

    assert result == 0
    outputs = dict(line.split("=", 1) for line in github_output.read_text().splitlines())
    assert outputs == {
        "has_files": "true",
        "staged_count": "2",
        "runnable_count": "1",
        "dropped_count": "1",
    }


def test_github_outputs_report_no_files_when_nothing_survives(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    canary_file = _write_project(tmp_path, [BROKEN_IMPORT_FILE])
    github_output = tmp_path / "github-output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(github_output))

    result = run_canary(
        canary_file,
        DESELECT_QUARANTINE_ARGS,
        collect_timeout_seconds=SHORT_COLLECT_TIMEOUT_SECONDS,
    )

    assert result == 0
    outputs = dict(line.split("=", 1) for line in github_output.read_text().splitlines())
    assert outputs["has_files"] == "false"
