import json
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
GATE = ROOT / "actions/validation-gate/gate.cjs"


def gate_succeeds(needs: dict[str, dict[str, str]], required: dict[str, bool | str]) -> bool:
    script = "const {validateGate}=require(process.argv[1]); validateGate(JSON.parse(process.argv[2]), JSON.parse(process.argv[3]));"
    return (
        subprocess.run(
            ["node", "-e", script, str(GATE), json.dumps(needs), json.dumps(required)], capture_output=True
        ).returncode
        == 0
    )


@pytest.mark.parametrize("required", [True, False])
@pytest.mark.parametrize("result", ["success", "failure", "cancelled", "skipped", "", "neutral"])
def test_gate_only_accepts_success_or_an_explicitly_unneeded_skip(required: bool, result: str) -> None:
    assert gate_succeeds({"lane": {"result": result}}, {"lane": required}) == (
        result == "success" or (not required and result == "skipped")
    )


@pytest.mark.parametrize(
    "needs,required",
    [({}, {"lane": True}), ({"lane": {"result": "success"}}, {}), ({"lane": {"result": "skipped"}}, {"lane": "false"})],
)
def test_gate_rejects_missing_edges_or_untyped_admission(
    needs: dict[str, dict[str, str]], required: dict[str, bool | str]
) -> None:
    assert not gate_succeeds(needs, required)


@pytest.mark.parametrize("decision", [False, True, None, "false", 0])
@pytest.mark.parametrize("planner", ["success", "failure", "skipped", "cancelled"])
def test_selected_lane_gate_requires_successful_planning_and_literal_false(decision, planner):
    needs = {"select-tests": {"result": planner}, "tests": {"result": "skipped"},
             "metadata": {"result": "success"}}
    script = """
    const {validateGate, selectedRequirements}=require(process.argv[1]);
    const needs=JSON.parse(process.argv[2]);
    validateGate(needs, selectedRequirements(needs, 'select-tests',
      {unit:JSON.parse(process.argv[3])}, {tests:['unit']}));
    """
    result = subprocess.run(["node", "-e", script, str(GATE), json.dumps(needs), json.dumps(decision)],
                            capture_output=True)
    assert (result.returncode == 0) == (planner == "success" and decision is False)


def test_selected_lane_gate_cannot_ignore_metadata_or_an_unmapped_job():
    script = """
    const {validateGate, selectedRequirements}=require(process.argv[1]);
    const needs={'select-tests':{result:'success'},tests:{result:'skipped'},metadata:{result:'skipped'}};
    validateGate(needs, selectedRequirements(needs,'select-tests',{unit:false},{tests:['unit']}));
    """
    assert subprocess.run(["node", "-e", script, str(GATE)], capture_output=True).returncode != 0
