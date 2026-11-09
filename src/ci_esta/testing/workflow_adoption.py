"""Check consumer wiring against its actual workflow and selector configuration."""

from __future__ import annotations

import itertools
import json
import re
from pathlib import Path

import yaml

from ci_esta.testing.lane_inference import EXTENDS, resolve
from ci_esta.workflow_graph import job_needs, lane_references, prerequisites

DEFAULT_GATE = "Validation gate"


def check(workflow: Path, lanes: Path | None, repo: Path = Path("."), gate_name: str = DEFAULT_GATE) -> str:
    """
    `lanes` is a lane file, complete or extending the workflow; None infers the lanes, as plan-work does.
    `gate_name` is the aggregate job's display name: keep a repository's existing required check rather than renaming it.
    A workflow with no lane conditions and no lane file has a plain gate: every job must reach it, and no lanes apply.
    Returns what was checked.
    """
    parsed = yaml.safe_load(workflow.read_text())
    jobs = parsed["jobs"]
    gate_ids = [name for name, job in jobs.items() if job.get("name", name) == gate_name]
    if len(gate_ids) != 1:
        raise ValueError(f"Exactly one aggregate job named {gate_name!r} is required (pass --gate for another name)")
    gate_id = gate_ids[0]
    gate = jobs[gate_id]
    action = [step for step in gate.get("steps", []) if "/validation-gate" in step.get("uses", "")]
    if len(action) != 1:
        raise ValueError("Use the shared validation-gate action")
    inputs = action[0].get("with", {})
    mapping = json.loads(inputs.get("lane-jobs", "{}"))
    needs = job_needs(gate)
    if inputs.get("needs") != "${{ toJSON(needs) }}" or inputs.get("required"):
        raise ValueError("The gate must validate all direct needs: needs: ${{ toJSON(needs) }}, without required")
    if lanes is None and not mapping and not any(lane_references(str(job.get("if", ""))) for job in jobs.values()):
        # A plain gate: no job is selected by lanes, so every job must reach the gate and succeed.
        _check_every_job_reaches(jobs, gate_id)
        return "Aggregate-gate contract passed: every job reaches the gate (no lanes)"
    document = json.loads(lanes.read_text()) if lanes is not None else None
    # A complete lane file names its lanes; an extending file or none needs the workflow's inferred lanes.
    if document is not None and EXTENDS not in document:
        configured = document["lanes"]
    else:
        configured = resolve(repo, "HEAD", "HEAD", lanes).config.lanes
    planner = inputs.get("planner", "select-tests")
    if planner not in needs:
        raise ValueError("The planner must be a direct gate prerequisite")
    if inputs.get("lanes") != "${{ needs." + planner + ".outputs.lanes || '{}' }}":
        raise ValueError("Pass the declared planner's lane output with an empty-object fallback")
    for name in needs:
        condition = str(jobs[name].get("if", ""))
        selected = lane_references(condition, planner)
        declared = mapping.get(name, [])
        if set(declared) != selected or any(lane not in configured for lane in declared):
            raise ValueError(f"Gate lane mapping differs from execution routing for {name}")
    if set(mapping) - set(needs):
        raise ValueError("Gate mapping refers to a job outside its prerequisites")
    _check_every_job_reaches(jobs, gate_id)
    _check_reuse_coverage(parsed.get("env") or {}, jobs, planner)
    return "Workflow lane and aggregate-gate contracts passed"


def _check_every_job_reaches(jobs: dict, gate_id: str) -> None:
    visited = prerequisites({name: job_needs(job) for name, job in jobs.items()}, [gate_id])
    if visited != set(jobs):
        raise ValueError(f"Validation jobs outside the aggregate gate: {sorted(set(jobs) - visited)}")


ENV_REFERENCE = re.compile(r"^\$\{\{\s*env\.([A-Za-z_][A-Za-z0-9_]*)\s*\}\}$")
MATRIX_REFERENCE = re.compile(r"\$\{\{\s*matrix\.([A-Za-z_][A-Za-z0-9_-]*)\s*\}\}")


def _check_reuse_coverage(workflow_env: dict, jobs: dict, planner: str) -> None:
    """
    A lane admitted as proven must name every job it gates in `lane-keys`, matrix cells included.

    resolve-lane-evidence turns a lane off when all of its listed keys are proven. A gated job the
    list omits, such as a newly added matrix cell, would then be skipped without proof, and its
    failure would pass the gate on the next push that changes nothing the receipt binds.
    """
    for job_id, job in jobs.items():
        environment = {**workflow_env, **(job.get("env") or {})}
        for step in job.get("steps", []):
            if "/resolve-lane-evidence" not in str(step.get("uses", "")):
                continue
            inputs = step.get("with") or {}
            if "lane-keys" not in inputs:
                continue
            names = _json_input(inputs.get("lanes", "{}"), environment, job_id, "lanes")
            lane_keys = _json_input(inputs["lane-keys"], environment, job_id, "lane-keys")
            for lane, keys in lane_keys.items():
                unknown = sorted(set(keys) - set(names))
                if not keys or unknown:
                    raise ValueError(f"{job_id}: lane-keys.{lane} must list keys of lanes (unknown: {unknown})")
                proven = {names[key] for key in keys}
                for gated_id, gated in jobs.items():
                    if lane not in lane_references(str(gated.get("if", "")), planner):
                        continue
                    missing = sorted(set(_job_names(gated_id, gated)) - proven)
                    if missing:
                        raise ValueError(
                            f"Lane {lane!r} is admitted from lane-keys in {job_id}, which omit jobs it gates: {missing}"
                        )


def _json_input(value: object, environment: dict, job_id: str, name: str) -> dict:
    text = str(value).strip()
    reference = ENV_REFERENCE.match(text)
    if reference:
        text = str(environment.get(reference.group(1), ""))
    try:
        parsed = json.loads(text)
    except ValueError as error:
        raise ValueError(f"{job_id}: {name} must be literal JSON or ${{{{ env.NAME }}}} for coverage checks") from error
    if not isinstance(parsed, dict):
        raise ValueError(f"{job_id}: {name} must be a JSON object")
    return parsed


def _job_names(job_id: str, job: dict) -> list[str]:
    """The check-run names GitHub gives a job: one per cell of a static matrix."""
    matrix = (job.get("strategy") or {}).get("matrix")
    if matrix is None:
        cells: list[dict] = [{}]
    elif isinstance(matrix, dict) and all(isinstance(axis, list) for axis in matrix.values()):
        cells = [dict(zip(matrix, values)) for values in itertools.product(*matrix.values())]
    else:
        raise ValueError(f"{job_id}: reuse coverage needs a static matrix of lists (no include, exclude or expressions)")
    template = job.get("name")
    names = []
    for cell in cells:
        if template is None:
            names.append(f"{job_id} ({', '.join(str(value) for value in cell.values())})" if cell else job_id)
            continue
        name = MATRIX_REFERENCE.sub(lambda match: str(cell[match.group(1)]), str(template))
        if "${{" in name:
            raise ValueError(f"{job_id}: reuse coverage cannot evaluate its name {template!r}")
        names.append(name)
    return names
