import ast
import json
from pathlib import Path

import yaml

from ci_esta.ci_observability.models import CiObservabilityReportV1

ACTION_PATH = Path("actions/ci-observability/action.yml")
SCHEMA_PATH = Path("actions/ci-observability/ci-observability-v1.schema.json")
WORKFLOW_PATH = Path(".github/workflows/trigger_downstream.yaml")
TEST_IMPACT_PATH = Path("actions/test-impact/action.yml")
SOURCE_ROOT = Path("src")
#: The ci-observability actions run this package's source with the runner image's own python3,
#: not the project's Python: ubuntu-24.04, GitHub's ubuntu-latest, ships 3.12.
RUNNER_PYTHON = (3, 12)
#: Modules the actions execute with that python3.
ACTION_ENTRY_POINTS = ["ci_esta.ci_observability.action", "ci_esta.ci_observability.enrichment.__main__"]


def test_action_contract_is_fail_open_and_future_compatible() -> None:
    action = yaml.safe_load(ACTION_PATH.read_text())
    report_step = action["runs"]["steps"][1]

    assert action["runs"]["using"] == "composite"
    assert action["inputs"]["required-gates-json"]["default"] == "[]"
    assert action["inputs"]["repository-signals-file"]["default"] == ""
    assert action["inputs"]["runner-sku-rates-json"]["default"] == "[]"
    assert action["inputs"]["post-sticky"]["default"] == "true"
    assert report_step["continue-on-error"] is True
    assert "reporting-runtime.sh" in report_step["run"]
    assert "ci_esta.ci_observability.action" in report_step["run"]
    assert action["runs"]["steps"][0]["uses"].startswith("astral-sh/setup-uv@")
    assert "sleep" not in ACTION_PATH.read_text()


def test_only_a_run_that_measured_a_full_suite_uploads_the_reference() -> None:
    action = yaml.safe_load(ACTION_PATH.read_text())
    upload = next(step for step in action["runs"]["steps"] if step["name"] == "Upload full-suite reference")

    assert action["inputs"]["test-selection-artifact"]["default"] == "test-impact-explanation"
    assert action["inputs"]["full-suite-reference-artifact"]["default"] == "ci-full-suite-reference-v1"
    assert upload["if"] == "${{ steps.report.outputs.full-suite-reference-file != '' }}"
    assert upload["continue-on-error"] is True
    assert upload["with"]["name"] == "${{ inputs.full-suite-reference-artifact }}"
    assert upload["with"]["path"] == "${{ steps.report.outputs.full-suite-reference-file }}"






def test_checked_in_schema_matches_the_pydantic_contract() -> None:
    assert json.loads(SCHEMA_PATH.read_text()) == CiObservabilityReportV1.model_json_schema()


def _module_file(module: str) -> Path | None:
    base = SOURCE_ROOT.joinpath(*module.split("."))
    for candidate in (base.with_suffix(".py"), base / "__init__.py"):
        if candidate.is_file():
            return candidate
    return None


def _runtime_closure() -> set[Path]:
    """Every first-party file the action entry points can import, including function-local imports."""
    seen: set[Path] = set()
    pending = list(ACTION_ENTRY_POINTS)
    while pending:
        module = pending.pop()
        parts = module.split(".")
        # Importing a.b.c runs a/__init__.py and a/b/__init__.py first.
        for depth in range(1, len(parts) + 1):
            path = _module_file(".".join(parts[:depth]))
            if path is None or path in seen:
                continue
            seen.add(path)
            package = ".".join(parts[:depth] if path.name == "__init__.py" else parts[: depth - 1])
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                if isinstance(node, ast.Import):
                    pending += [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom):
                    anchor = package.split(".")[: len(package.split(".")) - node.level + 1] if node.level else []
                    base = ".".join([*anchor, node.module] if node.module else anchor)
                    pending += [base, *(f"{base}.{alias.name}" for alias in node.names)]
    return seen


def test_every_module_the_actions_run_parses_on_the_runner_python() -> None:
    """
    A 3.14-only construct in this closure kills the sticky on every consumer PR.

    backend-common#233 shipped `except A, B:` (PEP 758) in the backend enrichment profile; the
    runner's python3 raised SyntaxError, and every gigaverse-backend PR lost its sticky.
    """
    closure = _runtime_closure()
    assert Path("src/ci_esta/ci_observability/enrichment/backend/artifacts.py") in closure

    unparseable = []
    for path in sorted(closure):
        try:
            ast.parse(path.read_text(encoding="utf-8"), filename=str(path), feature_version=RUNNER_PYTHON)
        except SyntaxError as error:
            unparseable.append(f"{path}:{error.lineno}: {error.msg}")
    assert unparseable == []


REPORT_WORKFLOW_PATH = Path(".github/workflows/report.yml")


def test_the_reusable_report_runs_its_own_commit_and_inherits_the_callers_permissions() -> None:
    workflow = yaml.safe_load(REPORT_WORKFLOW_PATH.read_text())
    steps = workflow["jobs"]["report"]["steps"]
    checkout, report = steps[0], steps[1]

    # A callee that declared pull-requests write would fail every read-only caller at startup.
    assert "permissions" not in workflow
    assert checkout["with"]["repository"] == "gigaverse-app/ci-esta"
    assert checkout["with"]["ref"] == "${{ job.workflow_sha }}"
    assert report["uses"] == "./.ci-esta/actions/ci-observability"
    inputs = workflow[True]["workflow_call"]["inputs"]
    assert inputs["post-sticky"]["default"] is False
    assert inputs["lane-selection-artifact"]["default"] == "test-lane-selection"
    assert inputs["analyze-critical-path"]["default"] is False
    assert report["with"]["analyze-critical-path"] == "${{ inputs.analyze-critical-path }}"
    assert report["with"]["job-dependencies-json"] == "${{ inputs.job-dependencies-json }}"


def test_reusable_report_allows_file_selection_artifacts_without_enabling_them_by_default() -> None:
    workflow = yaml.safe_load(REPORT_WORKFLOW_PATH.read_text())
    inputs = workflow[True]["workflow_call"]["inputs"]
    report = workflow["jobs"]["report"]["steps"][1]
    for artifact in ("test-selection-artifact", "full-suite-reference-artifact"):
        assert inputs[artifact]["default"] == ""
        assert report["with"][artifact] == "${{ inputs." + artifact + " }}"


def test_the_lane_section_and_sticky_key_are_on_by_default_and_unkeyed() -> None:
    action = yaml.safe_load(ACTION_PATH.read_text())

    assert action["inputs"]["lane-selection-artifact"]["default"] == "test-lane-selection"
    assert action["inputs"]["sticky-key"]["default"] == ""
