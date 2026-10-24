"""The public evidence action consumes scope before it can issue or reuse receipts."""

import json
import os
import subprocess
from pathlib import Path

import pytest
import yaml

ACTION = Path(__file__).resolve().parents[2] / "actions/resolve-lane-evidence"


@pytest.mark.parametrize(
    "selection,outcome,report,allowed,expected",
    [
        (
            '{"api":true,"browser":false}',
            "success",
            {"lanes": {"api": True, "browser": False}, "reason": "affected source"},
            False,
            {"api": True, "browser": False},
        ),
        ('{"api":false,"browser":false}', "failure", {}, True, {"api": True, "browser": True}),
        ("broken", "success", {}, True, {"api": True, "browser": True}),
        ('{"api":"false","browser":false}', "success", {}, True, {"api": True, "browser": False}),
        (
            '{"api":true,"browser":true}',
            "success",
            {"lanes": {"api": True, "browser": True}, "reason": "explicit full-suite checkpoint"},
            True,
            {"api": True, "browser": True},
        ),
        (
            '{"api":true,"browser":true}',
            "success",
            {"lanes": {"api": False, "browser": True}, "reason": "affected source"},
            True,
            {"api": True, "browser": True},
        ),
        (
            '{"api":false,"browser":false}',
            "success",
            {"lanes": {"api": False, "browser": False}, "reason": "no changes"},
            True,
            {"api": False, "browser": False},
        ),
    ],
)
def test_unverifiable_fresh_or_empty_scope_does_not_even_query_evidence(
    tmp_path, selection, outcome, report, allowed, expected
):
    script = yaml.safe_load((ACTION / "action.yml").read_text())["runs"]["steps"][0]["with"]["script"]
    plan = tmp_path / "report.json"
    plan.write_text(json.dumps(report))
    # No GitHub client is supplied. Accidentally entering evidence lookup must fail.
    result = subprocess.run(
        [
            "node",
            "-e",
            """
const outputs = {};
const AsyncFunction = Object.getPrototypeOf(async function(){}).constructor;
new AsyncFunction('core','require','process',process.env.SCRIPT)({setOutput:(k,v)=>outputs[k]=v},require,process)
.then(()=>console.log(JSON.stringify(outputs))).catch(e=>{console.error(e);process.exit(1);});
""",
        ],
        check=True,
        capture_output=True,
        text=True,
        env=os.environ
        | {
            "SCRIPT": script,
            "GITHUB_ACTION_PATH": str(ACTION),
            "SELECTION_KEYS": '["api","browser"]',
            "SELECTION": selection,
            "SELECTION_OUTCOME": outcome,
            "SELECTION_REPORT": str(plan),
            "ALLOW_REUSE": str(allowed).lower(),
            "EVIDENCE_LANES": '{"linux":"Linux tests","mac":"Mac tests"}',
        },
    )
    outputs = json.loads(result.stdout)
    assert json.loads(outputs["selection"]) == expected
    assert json.loads(outputs["context"]) == expected
    assert outputs["receipt"] == ""
    assert json.loads(outputs["reused"]) == {}
    assert json.loads(outputs["matrix"]) == ["linux", "mac"]


@pytest.mark.parametrize(
    "proof,expected",
    [
        ({}, ["linux", "mac"]),
        ({"linux": True}, ["mac"]),
        ({"mac": True}, ["linux"]),
        ({"linux": "true", "mac": 1}, ["linux", "mac"]),
        ({"linux": True, "mac": True}, ["linux", "mac"]),
    ],
)
def test_matrix_only_removes_literal_proof(proof, expected):
    result = subprocess.run(
        [
            "node",
            "-e",
            """
const {pendingMatrix} = require(process.env.MODULE);
console.log(JSON.stringify(pendingMatrix(['linux','mac'], JSON.parse(process.env.PROOF))));
""",
        ],
        capture_output=True,
        text=True,
        check=True,
        env=os.environ
        | {
            "MODULE": str(ACTION / "selection.cjs"),
            "PROOF": json.dumps(proof),
        },
    )
    assert json.loads(result.stdout) == expected
