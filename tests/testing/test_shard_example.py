"""Run the documented example through real planning, pytest and completion checks."""

import os
import subprocess
import sys
from pathlib import Path
from xml.etree import ElementTree

import pytest

ROOT = Path(__file__).resolve().parents[2]
RUNNER = ROOT / "examples/pytest-shards/run_shard.py"
VERIFIER = ROOT / "src/ci_esta/testing/evidence_scripts/verify.sh"


@pytest.mark.parametrize("shards", [1, 4])
def test_example_preserves_every_test_and_rejects_missing_evidence(tmp_path, shards):
    tests = tmp_path / "tests"
    tests.mkdir()
    for index in range(4):
        (tests / f"test_case_{index}.py").write_text("def test_passes(): assert True\n")
    (tmp_path / ".test_durations").write_text("{}")
    cli = [sys.executable, "-m", "ci_esta.testing.cli"]
    subprocess.run(
        [*cli, "plan", "--test-root", "tests", "--shards", str(shards), "--exact-files", "--output-dir", "splits"],
        cwd=tmp_path,
        check=True,
    )
    subprocess.run(
        [*cli, "run-local", "--shards", str(shards), "--log-dir", "logs", "--", sys.executable, str(RUNNER)],
        cwd=tmp_path,
        check=True,
    )
    cases = [
        case.attrib["classname"]
        for path in tmp_path.glob("junit-group-*.xml")
        for case in ElementTree.parse(path).getroot().iter("testcase")
    ]
    assert sorted(cases) == [f"tests.test_case_{index}" for index in range(4)]
    env = {**os.environ, "PLAN_SHARD_COUNT": str(shards), "PLAN_MODE": "full"}
    subprocess.run(["bash", str(VERIFIER)], cwd=tmp_path, env=env, check=True)
    (tmp_path / "pytest-status-group-1").unlink()
    assert subprocess.run(["bash", str(VERIFIER)], cwd=tmp_path, env=env).returncode != 0


def test_example_retains_test_failure_and_does_not_run_empty_shards(tmp_path):
    (tmp_path / "splits").mkdir()
    (tmp_path / "test_failure.py").write_text("def test_fails(): assert False\n")
    plan = tmp_path / "splits/group-1.txt"
    plan.write_text("test_failure.py\n")
    env = {**os.environ, "GV_PYTEST_SHARD_INDEX": "1"}
    assert subprocess.run([sys.executable, str(RUNNER)], cwd=tmp_path, env=env).returncode == 1
    assert (tmp_path / "pytest-status-group-1").read_text().strip() == "1"
    plan.write_text("")
    result = subprocess.run([sys.executable, str(RUNNER)], cwd=tmp_path, env=env, capture_output=True, text=True)
    assert result.returncode != 0
    assert "Empty assigned shard" in result.stderr
