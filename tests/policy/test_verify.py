import json

import pytest

from ci_esta.policy.verify import verify


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
