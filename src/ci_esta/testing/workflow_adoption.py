"""Check consumer wiring against its actual workflow and selector configuration."""
from __future__ import annotations

import json
import re
from pathlib import Path

import yaml


def check(workflow: Path, lanes: Path) -> None:
    jobs = yaml.safe_load(workflow.read_text())["jobs"]
    configured = json.loads(lanes.read_text())["lanes"]
    gate_ids = [name for name, job in jobs.items() if job.get("name") == "Validation gate"]
    if len(gate_ids) != 1:
        raise ValueError("Exactly one stable Validation gate is required")
    gate_id = gate_ids[0]
    gate = jobs[gate_id]
    action = [step for step in gate.get("steps", []) if "/validation-gate" in step.get("uses", "")]
    if len(action) != 1:
        raise ValueError("Use the shared validation-gate action")
    inputs = action[0].get("with", {})
    mapping = json.loads(inputs.get("lane-jobs", "{}"))
    needs = gate.get("needs", [])
    if isinstance(needs, str):
        needs = [needs]
    if inputs.get("needs") != "${{ toJSON(needs) }}" or inputs.get("required"):
        raise ValueError("Selected-lane gates must validate all direct needs through lane-jobs")
    planner = inputs.get("planner", "select-tests")
    if planner not in needs:
        raise ValueError("The planner must be a direct gate prerequisite")
    if inputs.get("lanes") != "${{ needs." + planner + ".outputs.lanes || '{}' }}":
        raise ValueError("Pass the declared planner's lane output with an empty-object fallback")
    for name in needs:
        condition = str(jobs[name].get("if", ""))
        selected = set(re.findall(r"fromJSON\(needs\." + re.escape(planner) +
                                   r"\.outputs\.lanes\)\.([a-zA-Z_][a-zA-Z_0-9]*)", condition))
        declared = mapping.get(name, [])
        if set(declared) != selected or any(lane not in configured for lane in declared):
            raise ValueError(f"Gate lane mapping differs from execution routing for {name}")
    if set(mapping) - set(needs):
        raise ValueError("Gate mapping refers to a job outside its prerequisites")
    visited = set()

    def visit(name):
        if name in visited:
            return
        visited.add(name)
        parents = jobs[name].get("needs", [])
        for parent in [parents] if isinstance(parents, str) else parents:
            visit(parent)

    visit(gate_id)
    if visited != set(jobs):
        raise ValueError(f"Validation jobs outside the aggregate gate: {sorted(set(jobs) - visited)}")
