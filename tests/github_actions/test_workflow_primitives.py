"""Exercise workflow primitives at their public composite-action boundary."""

import json
import os
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("live,expected", [("same", "true"), ("newer", "false")])
def test_current_head_uses_the_live_pull_request(live: str, expected: str) -> None:
    step = yaml.safe_load((ROOT / ".github/actions/current-pr-head/action.yml").read_text())["runs"]["steps"][0]
    script = """
const {strictGithub}=require(process.env.STRICT_FAKE);
const github=strictGithub({pulls:{get:async()=>({data:{head:{sha:process.env.LIVE_HEAD}}})}});
const AsyncFunction=Object.getPrototypeOf(async function(){}).constructor;
new AsyncFunction('github','context','core',process.env.ACTION_SCRIPT)(github,{repo:{owner:'org',repo:'repo'}},{notice:()=>{}}).then(console.log);
"""
    result = subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True, env=os.environ | {
        "STRICT_FAKE": str(ROOT / "tests/ci/github_rest_fake.cjs"), "ACTION_SCRIPT": step["with"]["script"],
        "PR_NUMBER": "123", "EXPECTED_HEAD_SHA": "same", "LIVE_HEAD": live,
    })
    assert result.stdout.strip() == expected


@pytest.mark.parametrize("changed", [".github/workflows/build.yml", "application.py"])
def test_changed_ci_inputs_are_classified_from_git(tmp_path: Path, changed: str) -> None:
    def git(*args: str) -> str:
        return subprocess.check_output(["git", "-C", str(tmp_path), "-c", "user.name=CI-esta", "-c", "user.email=ci@example.invalid", *args], text=True).strip()

    git("init", "-q")
    (tmp_path / ".github/workflows").mkdir(parents=True)
    (tmp_path / ".github/workflows/build.yml").write_text("name: before\n")
    (tmp_path / "application.py").write_text("before = True\n")
    git("add", ".")
    git("commit", "-qm", "baseline")
    base = git("rev-parse", "HEAD")
    (tmp_path / changed).write_text("changed: true\n")
    git("add", ".")
    git("commit", "-qm", "change")
    action = yaml.safe_load((ROOT / ".github/actions/collect-ci-changes/action.yml").read_text())
    output = tmp_path / "outputs"
    subprocess.run(["bash", "-e", "-o", "pipefail", "-c", action["runs"]["steps"][0]["run"]], cwd=tmp_path, check=True, env=os.environ | {
        "CI_PATHS": ".github", "EVENT_NAME": "push", "PR_BASE_SHA": "", "PUSH_BEFORE_SHA": base,
        "HEAD_SHA": git("rev-parse", "HEAD"), "GITHUB_OUTPUT": str(output), "RUNNER_TEMP": str(tmp_path),
    })
    result = output.read_text()
    assert f"has-files={json.dumps(changed.startswith('.github'))}" in result
    assert (changed in result) == changed.startswith(".github")
