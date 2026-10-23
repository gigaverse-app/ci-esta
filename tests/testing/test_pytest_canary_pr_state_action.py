from pathlib import Path

import yaml


def test_pr_state_action_enforces_head_sha_and_full_matrix_owned_state() -> None:
    action_path = Path("actions/pytest-canary-pr-state/action.yml")
    action = yaml.safe_load(action_path.read_text())

    assert action["inputs"]["state"]["description"]
    assert action["inputs"]["expected-head-sha"]["required"] is True
    assert action["inputs"]["pull-request-number"]["required"] is True
    step = action["runs"]["steps"][0]
    assert step["uses"].startswith("actions/github-script@")
    script = step["with"]["script"]
    assert "pull.head.sha !== expectedHeadSha" in script
    assert 'state === "red"' in script
    assert 'state === "green"' in script
    assert "issues.createLabel" in script
    assert "issues.addLabels" in script
    assert "issues.removeLabel" in script
    assert "Unsupported pytest canary PR state" in script


def test_shared_actions_readme_lists_pytest_canary_pr_state() -> None:
    readme = Path("actions/README.md").read_text()

    assert "`pytest-canary-pr-state`" in readme
