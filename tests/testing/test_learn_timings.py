"""Learn scheduling hints from real pytest reports without trusting broken evidence."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from ci_esta.testing.cli import main
from ci_esta.testing.timing_feedback import main as feedback


def test_real_pytest_report_drives_exact_file_shards(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    tests = tmp_path / "tests"
    tests.mkdir()
    for name in ("one", "two"):
        (tests / f"test_{name}.py").write_text("def test_passes():\n    assert 2 + 2 == 4\n")
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "--junitxml=timings.xml"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert main(["learn", "timings.xml", "--output", "durations.json"]) == 0
    durations = json.loads(Path("durations.json").read_text())
    assert set(durations) == {"tests/test_one.py", "tests/test_two.py"}
    assert all(value >= 0 for value in durations.values())
    assert (
        main(["plan", "--durations", "durations.json", "--shards", "2", "--exact-files", "--output-dir", "splits"]) == 0
    )
    planned = "\n".join(path.read_text() for path in Path("splits").glob("*.txt"))
    assert "tests/test_one.py" in planned
    assert "tests/test_two.py" in planned


@pytest.mark.parametrize(
    "contents",
    [
        "broken",
        "<unexpected/>",
        '<testsuite><testcase time="nan"/></testsuite>',
        '<testsuite><testcase time="-1"/></testsuite>',
        '<testsuite><testcase time="1"><failure/></testcase></testsuite>',
        '<testsuite errors="1"/>',
    ],
)
def test_invalid_or_failed_report_preserves_previous_manifest(tmp_path, contents):
    report = tmp_path / "junit.xml"
    report.write_text(contents)
    output = tmp_path / "durations.json"
    output.write_text('{"tests/old.py": 42}')
    with pytest.raises(SystemExit):
        main(["learn", str(report), "--output", str(output)])
    assert output.read_text() == '{"tests/old.py": 42}'


def test_missing_report_preserves_previous_manifest(tmp_path):
    output = tmp_path / "durations.json"
    output.write_text("{}")
    with pytest.raises(SystemExit):
        main(["learn", str(tmp_path / "missing.xml"), "--output", str(output)])
    assert output.read_text() == "{}"


def test_unmapped_cases_are_reported_and_not_used_as_paths(tmp_path, capsys):
    test = tmp_path / "test_ok.py"
    test.write_text("")
    report = tmp_path / "junit.xml"
    report.write_text(
        '<testsuite><testcase file="test_ok.py" time="2"/>'
        '<testcase file="../outside.py" time="9"/>'
        '<testcase file="test_ok.py" time="0"><skipped/></testcase></testsuite>'
    )
    output = tmp_path / "durations.json"
    assert main(["learn", str(report), "--working-directory", str(tmp_path), "--output", str(output)]) == 0
    assert json.loads(output.read_text()) == {"test_ok.py": 2}
    assert "unmapped_cases=1" in capsys.readouterr().out


def test_action_glob_retains_source_reports_and_writes_summary(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    Path("test_ok.py").write_text("")
    Path("junit-1.xml").write_text('<testsuite><testcase file="test_ok.py" time="2"/></testsuite>')
    monkeypatch.setenv("INPUT_JUNIT_PATTERN", "junit-*.xml")
    monkeypatch.setenv("INPUT_TIMING_OUTPUT", "durations.json")
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", "summary.md")
    feedback()
    assert json.loads(Path("durations.json").read_text()) == {"test_ok.py": 2}
    assert Path("junit-1.xml").exists()
    assert "Learned 1 test-file costs" in Path("summary.md").read_text()
