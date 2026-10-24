import json
from pathlib import Path

import pytest

from ci_esta.policy.verify import verify, verify_workflows


def test_contract_runner_executes_cli_and_rejects_wrong_expectation(tmp_path):
    policy = tmp_path / "policy.json"
    cases = tmp_path / "cases.json"
    policy.write_text(
        json.dumps({"profiles": {"legacy": {"include": ["*"], "occasions": ["pr"]}}, "work": [{"id": "unit"}]})
    )
    case = {"name": "docs", "request": {"occasion": "pr", "affected": []}, "expected": []}
    cases.write_text(json.dumps([case]))
    verify(policy, cases)
    case["expected"] = ["unit"]
    cases.write_text(json.dumps([case]))
    with pytest.raises(AssertionError, match="docs"):
        verify(policy, cases)


def test_workflow_contract_evaluates_actual_inputs_and_catches_disconnected_selector(tmp_path, monkeypatch):
    import yaml

    monkeypatch.chdir(tmp_path)
    policy = {"profiles": {"legacy": {"include": ["*"], "occasions": ["pr"]}}, "work": [{"id": "unit"}]}
    Path("policy.json").write_text(json.dumps(policy))
    inputs = {
        "policy": "policy.json",
        "occasion": "${{ github.event_name == 'pull_request' && 'pr' || 'manual' }}",
        "affected": "${{ steps.select.outputs.lanes }}",
    }
    workflow = {
        "jobs": {"plan": {"steps": [{"id": "policy", "uses": "example/plan-test-policy@revision", "with": inputs}]}}
    }
    Path("workflow.yml").write_text(yaml.safe_dump(workflow))
    case = {
        "name": "docs-only PR",
        "workflow": "workflow.yml",
        "job": "plan",
        "step": "policy",
        "context": {
            "github": {"event_name": "pull_request"},
            "steps": {"select": {"outputs": {"lanes": '{"unit":false}'}}},
        },
        "expected": [],
    }
    Path("workflow-cases.json").write_text(json.dumps([case]))
    verify_workflows(Path("workflow-cases.json"))
    inputs["affected"] = "null"
    Path("workflow.yml").write_text(yaml.safe_dump(workflow))
    with pytest.raises(AssertionError, match="docs-only PR"):
        verify_workflows(Path("workflow-cases.json"))
