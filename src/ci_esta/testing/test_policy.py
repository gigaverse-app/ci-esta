"""Exercise a consumer's actual policy action inputs through the shipped CLI."""

import json
import re
import tempfile
from pathlib import Path

import yaml

from ci_esta.policy import ExecutionPlan
from ci_esta.policy.cli import main
from ci_esta.resources import source_root
from ci_esta.testing.gha_expressions import evaluate_value


def plan_workflow(workflow: Path, job: str, context: dict, *, step: str = "policy") -> ExecutionPlan:
    """Render action defaults and workflow expressions; fail on invalid routing.

    Event fields and upstream selector outputs are the test boundaries. The
    production workflow, action defaults and planner determine the result.
    """
    document = yaml.safe_load(workflow.read_text(encoding="utf-8"))
    call = next(item for item in document["jobs"][job]["steps"] if item.get("id") == step)
    if "/plan-test-policy@" not in call.get("uses", ""):
        raise AssertionError("Expected the public plan-test-policy action")
    action = yaml.safe_load((source_root() / "actions/plan-test-policy/action.yml").read_text(encoding="utf-8"))
    inputs = {key: spec["default"] for key, spec in action["inputs"].items() if "default" in spec}
    inputs.update(call.get("with", {}))

    def render(value: object) -> str:
        def replace(match: re.Match[str]) -> str:
            resolved = evaluate_value(match[0], context)
            return "" if resolved is None else resolved if isinstance(resolved, str) else json.dumps(resolved)

        return re.sub(r"\$\{\{.*?\}\}", replace, str(value), flags=re.DOTALL)

    root = workflow.resolve().parents[2]
    with tempfile.TemporaryDirectory() as directory:
        destination = Path(directory) / "plan.json"
        args = ["--output", str(destination), "--github-output", ""]
        for key, value in inputs.items():
            if key == "output":
                continue
            value = render(value)
            if key in {"policy", "lanes", "inventory"} and value:
                value = str(root / value)
            args.extend([f"--{key}", value])
        if main(args) != 0:
            raise AssertionError("Production policy inputs failed planning")
        return ExecutionPlan.model_validate_json(destination.read_text(encoding="utf-8"))
