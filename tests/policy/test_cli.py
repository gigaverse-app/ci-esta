import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from ci_esta.policy.cli import main


def configure(tmp_path):
    path = tmp_path / "policy.json"
    path.write_text(
        json.dumps(
            {
                "profiles": {"legacy": {"occasions": ["pr", "manual"], "include": ["*"]}},
                "work": [{"id": "python"}, {"id": "browser"}],
            }
        )
    )
    return [
        "--policy",
        str(path),
        "--profile",
        "legacy",
        "--occasion",
        "pr",
        "--revision",
        "abc",
        "--output",
        str(tmp_path / "plan.json"),
        "--github-output",
        str(tmp_path / "outputs"),
    ]


def test_cli_consumes_complete_lane_selection_and_roundtrips_plan(tmp_path):
    args = configure(tmp_path)
    assert main([*args, "--affected", '{"python": true, "browser": false}']) == 0
    output = dict(line.split("=", 1) for line in (tmp_path / "outputs").read_text().splitlines())
    assert json.loads(output["admitted"]) == {"python": True, "browser": False}
    assert json.loads(output["plan"]) == json.loads((tmp_path / "plan.json").read_text())


@pytest.mark.parametrize("affected", ['{"python": true}', '{"python": "false", "browser": false}', "42"])
def test_invalid_selector_output_removes_stale_plan(tmp_path, affected):
    args = configure(tmp_path)
    assert main(args) == 0
    assert main([*args, "--affected", affected]) == 2
    assert not (tmp_path / "plan.json").exists()


@pytest.mark.parametrize("use_defaults", [False, True])
def test_actual_action_shell_calls_shipped_planner(tmp_path, use_defaults):
    args = configure(tmp_path)
    root = Path(__file__).resolve().parents[2]
    action = yaml.safe_load((root / "actions/plan-test-policy/action.yml").read_text())
    step = action["runs"]["steps"][1]
    # Only the remote setup boundary is substituted. Execute the exact shipped
    # action shell and planner using the installed package, with no application deps.
    shim = tmp_path / "uv"
    shim.write_text('#!/bin/sh\nwhile [ "$1" != python ]; do shift; done\nshift\nexec "' + sys.executable + '" "$@"\n')
    shim.chmod(0o755)
    environment = {
        **os.environ,
        "PATH": f"{tmp_path}:{os.environ['PATH']}",
        "SHARED_ACTION_PATH": str(root / "actions/plan-test-policy"),
        "POLICY": "" if use_defaults else args[1],
        "WORK": '["python", "browser"]' if use_defaults else "",
        "LANES": "",
        "PROFILE": "legacy",
        "OCCASION": "pr",
        "REVISION": "abc",
        "AFFECTED": '{"python": false, "browser": true}',
        "REQUESTED": "null",
        "TARGET_ENVIRONMENT": "",
        "DEPLOYED_REVISION": "",
        "INVENTORY": "",
        "PLAN_OUTPUT": str(tmp_path / "plan.json"),
        "GITHUB_OUTPUT": str(tmp_path / "outputs"),
    }
    subprocess.run(["bash", "-e", "-c", step["run"]], env=environment, check=True)
    output = json.loads((tmp_path / "plan.json").read_text())
    assert [(item["work"]["id"], item["status"]) for item in output["decisions"]] == [
        ("python", "unaffected"),
        ("browser", "run"),
    ]
