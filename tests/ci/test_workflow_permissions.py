"""Publish calls the CI workflow; GitHub refuses to start a called workflow whose jobs ask for more than the caller grants.

A called workflow that requests a scope its caller does not grant ends in `startup_failure` before any job runs, so
nothing is published. That lost pytest-quint-connect 1.2.0 and pytest-selective 0.4.3 when a CI job gained a scope
the Publish call did not grant.
"""
# gv:test-dependency: .github/workflows/ci.yml
# gv:test-dependency: .github/workflows/release.yml
import json
import re
from pathlib import Path

import pytest
import yaml

from ci_esta.testing.gha_expressions import evaluate

WORKFLOWS = Path(__file__).resolve().parents[2] / ".github/workflows"
LEVEL = {"none": 0, "read": 1, "write": 2}
CI = "./.github/workflows/ci.yml"


def workflow(name: str) -> dict:
    return yaml.safe_load((WORKFLOWS / name).read_text(encoding="utf-8"))


def scopes(block: object) -> dict[str, str]:
    # `read-all`/`write-all` shorthands would hide the per-scope comparison; keep explicit scope maps.
    assert isinstance(block, dict), f"use an explicit per-scope permissions map, not {block!r}"
    return block


def requested(called: dict) -> dict[str, str]:
    """The highest level each scope is requested at, across the called workflow and every one of its jobs."""
    wanted: dict[str, str] = {}
    blocks = [called.get("permissions", {}), *(job.get("permissions", {}) for job in called["jobs"].values())]
    for block in blocks:
        for scope, level in scopes(block).items():
            if LEVEL[level] > LEVEL[wanted.get(scope, "none")]:
                wanted[scope] = level
    return wanted


def test_publish_grants_every_permission_ci_requests() -> None:
    publish = workflow("release.yml")
    calls = {name: job for name, job in publish["jobs"].items() if job.get("uses") == CI}
    assert calls, "Publish no longer calls ci.yml; update this test"
    wanted = requested(workflow("ci.yml"))
    assert wanted, "ci.yml requests no permissions; update this test"
    for name, job in calls.items():
        # A call job without its own block inherits the caller's workflow-level permissions.
        granted = scopes(job.get("permissions", publish.get("permissions", {})))
        missing = {scope: level for scope, level in wanted.items() if LEVEL[level] > LEVEL[granted.get(scope, "none")]}
        assert not missing, f"release.yml job {name!r} must grant {missing} to ci.yml, or Publish fails at startup"


def test_publish_call_grants_its_permissions_explicitly() -> None:
    """Inheritance couples the call to unrelated workflow-level edits; the call states what CI needs."""
    publish = workflow("release.yml")
    for name, job in publish["jobs"].items():
        if job.get("uses") == CI:
            assert "permissions" in job, f"release.yml job {name!r} relies on inherited permissions"


def test_dispatch_only_jobs_stay_off_when_publish_calls_ci() -> None:
    """
    Publish re-dispatched on a tag calls ci.yml with workflow_call. Inside the call `github.event_name`
    is still the caller's workflow_dispatch, while ci.yml's own dispatch inputs are empty. A condition
    such as `inputs.timing-example != 'off'` is then true, the optional example ran, and v1.12.0's
    Publish could not succeed.
    """
    workflow = yaml.safe_load((WORKFLOWS / "ci.yml").read_text(encoding="utf-8"))
    risky = {
        name: job["if"]
        for name, job in workflow["jobs"].items()
        if re.search(r"inputs\.[\w-]+\s*!=", str(job.get("if", "")))
    }
    assert not risky, f"an empty dispatch input satisfies these conditions under workflow_call: {risky}"
    example = workflow["jobs"]["timing-example"]["if"]
    triggers = workflow.get("on", workflow.get(True))  # YAML 1.1 reads the `on` key as true
    modes = [mode for mode in triggers["workflow_dispatch"]["inputs"]["timing-example"]["options"] if mode != "off"]
    assert json.dumps(modes, separators=(",", ":")) in example.replace("'", '"')


@pytest.mark.parametrize("event", ["workflow_dispatch", "release"])
@pytest.mark.parametrize("mode", [None, "", "off", "alpha", "beta", "verify"])
def test_optional_timing_example_requires_an_explicit_manual_mode(event: str, mode: str | None) -> None:
    # A manual Publish call inherits workflow_dispatch but supplies no CI inputs.
    inputs = {} if mode is None else {"timing-example": mode}
    context = {"github": {"event_name": event}, "inputs": inputs}
    condition = workflow("ci.yml")["jobs"]["timing-example"]["if"]
    assert evaluate(condition, context) == (event == "workflow_dispatch" and mode in {"alpha", "beta", "verify"})
