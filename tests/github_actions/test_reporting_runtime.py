"""Reporting actions share dependencies without activating the consumer project."""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.skipif(shutil.which("uv") is None, reason="requires the real action runtime")
def test_reporting_and_timing_share_a_locked_isolated_environment(tmp_path):
    consumer = tmp_path / "consumer"
    consumer.mkdir()
    (consumer / "pyproject.toml").write_text("invalid consumer project must not be loaded")
    sentinel = consumer / ".venv" / "keep"
    sentinel.parent.mkdir()
    sentinel.write_text("preserve")
    env = dict(os.environ, RUNNER_TEMP=str(tmp_path), UV_PROJECT_ENVIRONMENT=str(sentinel.parent),
               GITHUB_RUN_ID="7", GITHUB_RUN_ATTEMPT="2", GITHUB_SHA="a" * 40,
               GITHUB_EVENT_PATH="", BUN_EXECUTION_FILE=str(consumer / "bun-execution.json"))
    helper = ROOT / "scripts/ci/reporting-runtime.sh"

    def invoke(*args):
        result = subprocess.run([shutil.which("bash"), helper.as_posix(), *args], cwd=consumer, env=env,
                                capture_output=True, text=True)
        assert result.returncode == 0, result.stderr
        return result.stdout.strip()

    interpreter = Path(invoke("--prepare"))
    stamp = interpreter.stat().st_mtime_ns
    invoke("ci_esta.ci_observability.enrichment", "capture-pytest", "--shard-count", "2",
           "--wall-time", "3", "--total-time", "5", "--out", "timings.json")
    assert json.loads((consumer / "timings.json").read_text())["shard_count"] == 2
    (consumer / "bun-execution.json").write_text(json.dumps({
        "mode": "full", "reason": "Full checkpoint", "testedSha": "b" * 40,
        "bunVersion": "1.4.2", "totalFiles": 2, "executedFiles": ["one.test.ts"], "exitCode": 0,
    }))
    invoke("ci_esta.testing.bun.cli", "report")
    report = json.loads((consumer / "ci-work-selection.json").read_text())
    assert report["decisions"][0]["execution"]["status"] == "incomplete"
    assert report["head_sha"] != report["decisions"][0]["execution"]["tested_sha"]
    assert Path(invoke("--prepare")) == interpreter
    assert interpreter.stat().st_mtime_ns == stamp
    assert sentinel.read_text() == "preserve"
    assert not (consumer / "uv.lock").exists()
    assert not list(tmp_path.glob("**/site-packages/ci_esta*")), "run checked-out source, no package build"
