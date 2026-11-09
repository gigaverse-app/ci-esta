"""Publish calls the CI workflow; GitHub refuses to start a called workflow whose jobs ask for more than the caller grants.

A called workflow that requests a scope its caller does not grant ends in `startup_failure` before any job runs, so
nothing is published. That lost pytest-quint-connect 1.2.0 and pytest-selective 0.4.3 when a CI job gained a scope
the Publish call did not grant.
"""
# gv:test-dependency: .github/workflows/ci.yml
# gv:test-dependency: .github/workflows/release.yml
from pathlib import Path

import yaml

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
