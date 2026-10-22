"""Run the packaged shell driver against a recording Docker/AWS command boundary."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

# The fake boundary returns only external command responses; scenario order,
# filenames, timing rows and resource cleanup are executed by the real driver.
COMMAND = """#!/usr/bin/env python3
import json, os, pathlib, sys
args = sys.argv[1:]
with open(os.environ["CALLS"], "a") as stream:
    stream.write(json.dumps([pathlib.Path(sys.argv[0]).name, *args]) + "\\n")
if pathlib.Path(sys.argv[0]).name == "aws":
    print("test-password")
elif args[:2] == ["volume", "inspect"]:
    sys.exit(1)
elif args[:2] == ["buildx", "imagetools"]:
    print('{"layers":[]}')
elif args[0] == "exec":
    if "login" in args:
        sys.stdin.read()
    if "pull" in args and os.environ.get("FAIL_PULL"):
        sys.exit(42)
    print("{}")
"""


@pytest.mark.parametrize("fail_pull", [False, True])
def test_named_scenarios_and_cleanup_through_real_shell(tmp_path: Path, fail_pull: bool) -> None:
    binaries = tmp_path / "bin"
    binaries.mkdir()
    for name in ("docker", "aws"):
        command = binaries / name
        command.write_text(COMMAND)
        command.chmod(0o755)
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    digest = "sha256:" + "a" * 64
    (evidence / "inputs.json").write_text(
        json.dumps(
            {
                "repository": "registry.example/repo",
                "prefix": "test-probe",
                "dind": "docker@" + digest,
                "pull_samples": 1,
                "pull_sequence": ["cold", "source", "os"],
            }
        )
    )
    (evidence / "results.jsonl").write_text(
        "\n".join(
            json.dumps({"arm": arm, "scenario": scenario, "sample": 0, "digest": digest})
            for arm in ("baseline", "candidate")
            for scenario in ("cold", "source", "os")
        )
    )
    calls = tmp_path / "calls.jsonl"
    env = dict(os.environ, PATH=f"{binaries}:{os.environ['PATH']}", CALLS=str(calls))
    if fail_pull:
        env["FAIL_PULL"] = "1"
    result = subprocess.run(
        [sys.executable, "-c", "from ci_esta.image_evidence.cli import main; main()", "pulls", str(evidence)],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    recorded = [json.loads(line) for line in calls.read_text().splitlines()]
    arms = ("baseline",) if fail_pull else ("baseline", "candidate")
    for arm in arms:
        assert ["docker", "rm", "-f", f"test-probe-pull-{arm}-0"] in recorded
        assert ["docker", "volume", "rm", f"test-probe-pull-{arm}-0-store"] in recorded
    if fail_pull:
        assert result.returncode != 0
    else:
        assert result.returncode == 0, result.stderr
        rows = [json.loads(line) for line in (evidence / "pulls.jsonl").read_text().splitlines()]
        assert [(row["arm"], row["scenario"]) for row in rows] == [
            (arm, scenario) for arm in arms for scenario in ("cold", "source", "os")
        ]
        assert (evidence / "candidate-os-manifest.json").is_file()
        assert not list(evidence.glob("*bump*"))
