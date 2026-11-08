"""Every runtime test, build and smoke command must be admitted by dependency selection."""
# gv:test-dependency: .github/workflows/ci.yml
# gv:test-dependency: .github/workflows/public-actions.yml

import json
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
RUNTIME = (
    "pytest ",
    "-m unittest",
    "node --test",
    "run_ci_tests.py",
    "smoke_distribution.py",
    "check_wheel.py",
    "check_core_is_framework_free.py",
    "scripts/tutorial.py",
    "ci-esta-pytest",
    # Package builds and metadata checks are selected work too, not unconditional quality.
    "uv build",
    "twine check",
)


def test_runtime_commands_have_selection_and_failure_fallback():
    for path in (ROOT / ".github/workflows").glob("*.y*ml"):
        # Release/full checkpoints deliberately execute everything.
        if path.name not in {"ci.yml", "public-actions.yml"}:
            continue
        jobs = yaml.safe_load(path.read_text())["jobs"]
        for name, job in jobs.items():
            for step in job.get("steps", []):
                command = step.get("run", "")
                if not any(marker in command for marker in RUNTIME):
                    continue
                admission = job.get("if", "") + " " + step.get("if", "")
                assert "needs." in admission and "result != 'success'" in admission, (path.name, name, command)
                assert "lanes" in admission, (path.name, name, command)


def test_admission_names_only_configured_lanes():
    # A misspelled lane reads as null, which silently skips the work it guards.
    configured = set(json.loads((ROOT / ".github/test-lanes.json").read_text())["lanes"])
    for name in ("ci.yml", "public-actions.yml"):
        text = (ROOT / ".github/workflows" / name).read_text()
        referenced = set(re.findall(r"outputs\.lanes(?: \|\| '\{\}')?\)\.([a-z_][a-z0-9_]*)", text))
        assert referenced, name
        assert referenced <= configured, (name, referenced - configured)


def test_public_smoke_is_selected_and_requires_successful_planning():
    path = ROOT / ".github/workflows/public-actions.yml"
    if not path.exists():
        return
    jobs = yaml.safe_load(path.read_text())["jobs"]
    smoke = jobs["public-actions"]
    assert smoke["needs"] == "select-tests"
    assert "needs.select-tests.result != 'success'" in smoke["if"]
    assert "lanes" in smoke["if"]
    assert any(
        "exit 1" in step.get("run", "") and "needs.select-tests.result" in step.get("if", "") for step in smoke["steps"]
    )


def test_ordinary_pushes_do_not_force_full_tests():
    for path in (ROOT / ".github/workflows").glob("*.y*ml"):
        jobs = yaml.safe_load(path.read_text()).get("jobs", {})
        for job in jobs.values():
            for step in job.get("steps", []):
                if any(action in step.get("uses", "") for action in ("plan-lanes", "plan-work")) or step.get("id") == "files":
                    full = step.get("with", {}).get("full", "auto")
                    assert "github.event_name != 'pull_request'" not in str(full), path
                    assert full == "auto" or "workflow_dispatch" in str(full), path


def test_dogfood_planners_have_weekly_full_checkpoints_without_receipt_reuse():
    for name, planner in (("ci.yml", "plan"), ("public-actions.yml", "select-tests")):
        workflow = yaml.safe_load((ROOT / ".github/workflows" / name).read_text())
        assert workflow[True]["schedule"]
        steps = workflow["jobs"][planner]["steps"]
        selection = next(step for step in steps if step.get("id") in {"selection", "select"})
        assert selection["uses"] == "./actions/plan-work"
        assert selection.get("with", {}).get("full", "auto") == "auto"
        evidence = next(step for step in steps if step.get("id") == "evidence")
        assert set(re.findall(r"github.event_name == '([^']+)'", evidence["if"])) == {"pull_request", "push"}
        assert "!contains(github.event.pull_request.labels.*.name, 'test:full')" in evidence["if"]
