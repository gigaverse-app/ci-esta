"""Checkpoint dispatch validates every target before starting any work."""
import base64
import json

import httpx
import pytest

from ci_esta.checkpoint import Checkpoint, dispatch, main
from ci_esta.ci_observability.github import GitHubActionsClient


@pytest.mark.parametrize("invalid", [False, True])
def test_dispatch_preflights_all_targets_and_uses_default_branch(invalid):
    posts = []

    def respond(request):
        if request.method == "POST":
            posts.append(json.loads(request.content))
            return httpx.Response(204)
        if request.url.path.endswith("/example/repo"):
            return httpx.Response(200, json={"default_branch": "trunk"})
        assert request.url.params["ref"] == "trunk"
        source = "on:\n  workflow_dispatch:\n    inputs:\n      full:\n        type: boolean\n"
        if invalid and request.url.path.endswith("smoke.yml"):
            source = "on: push"
        return httpx.Response(200, json={"encoding": "base64", "content": base64.b64encode(source.encode()).decode()})

    client = GitHubActionsClient("example/repo", "test", transport=httpx.MockTransport(respond))
    try:
        config = Checkpoint(workflows=["ci.yml", "smoke.yml"], inputs={"full": True})
        if invalid:
            with pytest.raises(ValueError, match="workflow_dispatch"):
                dispatch(client, config)
            assert posts == []
        else:
            result = dispatch(client, config)
            assert result.ref == "trunk"
            assert result.workflows == config.workflows
            assert posts == [{"ref": "trunk", "inputs": {"full": True}}] * 2
    finally:
        client.close()


def test_dry_run_checks_inputs_without_dispatching():
    def respond(request):
        assert request.method == "GET"
        source = "on:\n  workflow_dispatch:\n    inputs:\n      environment:\n        required: true\n"
        return httpx.Response(200, json={"encoding": "base64", "content": base64.b64encode(source.encode()).decode()})

    client = GitHubActionsClient("example/repo", "test", transport=httpx.MockTransport(respond))
    try:
        with pytest.raises(ValueError, match="required"):
            dispatch(client, Checkpoint(ref="candidate"), dry_run=True)
        with pytest.raises(ValueError, match="unknown"):
            dispatch(client, Checkpoint(ref="candidate", inputs={"typo": "x"}), dry_run=True)
        assert dispatch(client, Checkpoint(ref="candidate", inputs={"environment": "test"}), dry_run=True).ref == "candidate"
    finally:
        client.close()


@pytest.mark.parametrize("workflows", [[], ["ci.yml", "ci.yml"], ["../ci.yml"]])
def test_invalid_target_lists_are_rejected(workflows):
    with pytest.raises(ValueError):
        Checkpoint(workflows=workflows)


def test_init_has_usable_defaults_and_preserves_existing_work(tmp_path):
    import yaml
    output = tmp_path / "workflows/weekly.yml"
    assert main(["init", "--output", str(output)]) == 0
    original = output.read_text()
    workflow = yaml.safe_load(original)
    assert workflow["on"]["schedule"] == [{"cron": "17 3 * * 1"}]
    assert workflow["permissions"] == {"contents": "read", "actions": "write"}
    with pytest.raises(FileExistsError):
        main(["init", "--output", str(output), "--ref", "other"])
    assert output.read_text() == original
