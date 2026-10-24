"""The action runtime must not discover, install or modify the consumer project."""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.skipif(shutil.which("uv") is None, reason="uv is required to exercise the action runtime")
def test_locked_runtime_preserves_consumer_and_relative_reports(tmp_path):
    consumer = tmp_path / "consumer"
    consumer.mkdir()
    (consumer / "pyproject.toml").write_text("This deliberately is not a valid Python project")
    (consumer / ".venv").mkdir()
    sentinel = consumer / ".venv" / "keep"
    sentinel.write_text("consumer environment")
    (consumer / "tests").mkdir()
    (consumer / "tests/test_a.py").write_text("def test_a(): pass\n")
    (consumer / "junit.xml").write_text(
        '<testsuite tests="1"><testcase file="tests/test_a.py" name="test_a" time="2"/></testsuite>'
    )
    env = dict(os.environ, RUNNER_TEMP=str(tmp_path), UV_PROJECT_ENVIRONMENT=str(consumer / ".venv"),
               INPUT_HISTORY_KEY="", INPUT_JUNIT_PATTERN="junit.xml", INPUT_TIMING_OUTPUT="durations.json",
               GITHUB_STEP_SUMMARY=str(tmp_path / "summary"))
    result = subprocess.run(["bash", str(ROOT / "scripts/ci/timing-runtime.sh"),
                             "ci_esta.testing.timing_feedback"], cwd=consumer, env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads((consumer / "durations.json").read_text()) == {"tests/test_a.py": 2.0}
    assert sentinel.read_text() == "consumer environment"
    assert not (consumer / "uv.lock").exists()
    assert "Building ci-esta" not in result.stderr
    assert not list((tmp_path / "ci-esta-timing-runtime").rglob("ci_esta-*.dist-info"))
