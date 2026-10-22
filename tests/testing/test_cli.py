import json
import sys
from pathlib import Path

import pytest

from ci_esta.testing.cli import main

QUARANTINED_TEST_SOURCE = "import pytest\n\n@pytest.mark.quarantine\ndef test_quarantined():\n    assert True\n"
BROKEN_IMPORT_TEST_SOURCE = (
    "import module_that_does_not_exist_anywhere\n\ndef test_never_collected():\n    assert True\n"
)
PASSING_TEST_SOURCE = "def test_passes():\n    assert True\n"


def test_plan_cli_writes_requested_shards(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_example.py").touch()
    durations = tmp_path / ".test_durations"
    durations.write_text(json.dumps({"tests/test_example.py::test_one": 1.0}))

    result = main(["plan", "--durations", str(durations), "--shards", "2", "--output-dir", "splits"])

    assert result == 0
    assert (tmp_path / "splits/group-1.txt").exists()
    assert (tmp_path / "splits/group-2.txt").exists()


def test_run_local_cli_passes_stable_shard_identity(tmp_path: Path) -> None:
    worker = tmp_path / "worker.py"
    worker.write_text(
        "import os\n"
        "from pathlib import Path\n"
        "index = os.environ['GV_PYTEST_SHARD_INDEX']\n"
        "count = os.environ['GV_PYTEST_SHARD_COUNT']\n"
        f"Path({str(tmp_path)!r}, f'{{index}}-of-{{count}}').touch()\n"
    )

    result = main(
        [
            "run-local",
            "--shards",
            "2",
            "--log-dir",
            str(tmp_path / "logs"),
            "--",
            sys.executable,
            str(worker),
        ]
    )

    assert result == 0
    assert {path.name for path in tmp_path.glob("*-of-2")} == {"1-of-2", "2-of-2"}


def test_run_local_cli_requires_a_command(tmp_path: Path) -> None:
    with pytest.raises(SystemExit, match="2"):
        main(["run-local", "--shards", "2", "--log-dir", str(tmp_path)])


def test_coverage_cli_enforces_floor_from_existing_xml(tmp_path: Path) -> None:
    report = tmp_path / "coverage.xml"
    report.write_text('<coverage line-rate="0.61"/>')

    assert main(["coverage", str(report), "--fail-under", "62"]) == 1
    assert main(["coverage", str(report), "--fail-under", "60"]) == 0


def test_canary_cli_writes_whole_failing_test_files(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_example.py").touch()
    report = tmp_path / "junit.xml"
    report.write_text(
        '<testsuite><testcase file="tests/test_example.py" name="test_one"><failure /></testcase></testsuite>'
    )
    output = tmp_path / "canary.txt"

    result = main(
        [
            "canary",
            str(report),
            "--output",
            str(output),
            "--max-files",
            "5",
            "--working-directory",
            str(tmp_path),
        ]
    )

    assert result == 0
    assert output.read_text() == "tests/test_example.py\n"
    assert "selected_files=1 failing_files=1 terminal_failures=1 truncated=false" in capsys.readouterr().out


def _write_canary_run_project(tmp_path: Path, sources: dict[str, str]) -> Path:
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    for file_path, source in sources.items():
        (tmp_path / file_path).write_text(source)
    canary_file = tmp_path / "pytest-failure-canary.txt"
    canary_file.write_text("".join(f"{entry}\n" for entry in sources))
    return canary_file


def test_canary_run_cli_falls_through_when_all_files_are_deselected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(tmp_path)
    canary_file = _write_canary_run_project(tmp_path, {"tests/test_quarantined.py": QUARANTINED_TEST_SOURCE})

    result = main(["canary-run", str(canary_file), "--", "-m", "not quarantine", "-p", "no:cacheprovider"])

    assert result == 0
    assert "falling through to the full matrix" in capsys.readouterr().out


def test_canary_run_cli_prune_only_rewrites_the_paths_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    canary_file = _write_canary_run_project(
        tmp_path,
        {"tests/test_broken_import.py": BROKEN_IMPORT_TEST_SOURCE, "tests/test_passing.py": PASSING_TEST_SOURCE},
    )

    result = main(
        [
            "canary-run",
            str(canary_file),
            "--prune-only",
            "--",
            "-m",
            "not quarantine",
            "-p",
            "no:cacheprovider",
        ]
    )

    assert result == 0
    assert canary_file.read_text() == "tests/test_passing.py\n"


def test_canary_run_cli_rejects_output_without_prune_only(tmp_path: Path) -> None:
    canary_file = tmp_path / "pytest-failure-canary.txt"
    canary_file.write_text("")

    with pytest.raises(SystemExit):
        main(["canary-run", str(canary_file), "--output", str(tmp_path / "pruned.txt")])
