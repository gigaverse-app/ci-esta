"""Run project-owned routing examples through the installed CLI, without pytest.

Usage: python -m ci_esta.policy.verify POLICY CASES
Cases are a JSON list with name, request (CLI fields), affected and expected IDs.
This is a contract-test helper, never a substitute for test execution evidence.
"""

import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

from ci_esta.testing.gha_expressions import evaluate_value


def verify(policy: Path, cases: Path) -> None:
    for case in json.loads(cases.read_text()):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "plan.json"
            args = [
                sys.executable,
                "-m",
                "ci_esta.policy.cli",
                "--policy",
                str(policy),
                "--output",
                str(output),
                "--github-output",
                "",
                "--revision",
                "contract-revision",
            ]
            for field, value in case["request"].items():
                args.extend(
                    [
                        "--" + field.replace("_", "-"),
                        json.dumps(value) if field in {"affected", "requested"} else str(value),
                    ]
                )
            result = subprocess.run(args, text=True, capture_output=True)
            expected_exit = case.get("exit", 0)
            if result.returncode != expected_exit:
                raise AssertionError(
                    f"{case['name']}: exit {result.returncode}, expected {expected_exit}: {result.stderr}"
                )
            if expected_exit == 0:
                plan = json.loads(output.read_text())
                actual = sorted(item["work"]["id"] for item in plan["decisions"] if item["status"] == "run")
                if actual != sorted(case["expected"]):
                    raise AssertionError(f"{case['name']}: {actual}, expected {case['expected']}")
                if "fresh" in case:
                    if any(item["fresh"] != case["fresh"] for item in plan["decisions"] if item["status"] == "run"):
                        raise AssertionError(f"{case['name']}: incorrect freshness")
            print(f"PASS {case['name']}")


def verify_workflows(cases: Path) -> None:
    """Evaluate actual action inputs, then execute the same CLI as the action.

    Uses CI-esta's existing limited expression evaluator. Unsupported expression
    syntax fails the contract instead of simulating a successful workflow.
    Remote event/selector outputs are fixture boundaries, never admission results.
    """
    for case in json.loads(cases.read_text()):
        workflow = yaml.safe_load(Path(case["workflow"]).read_text())
        step = next(step for step in workflow["jobs"][case["job"]]["steps"] if step.get("id") == case["step"])
        if "/plan-test-policy@" not in step.get("uses", ""):
            raise AssertionError(f"{case['name']}: expected the public policy action")

        def render(value: str) -> str:
            def replace(match: re.Match[str]) -> str:
                resolved = evaluate_value(match[0], case["context"])
                if resolved is None:
                    return ""
                return resolved if isinstance(resolved, str) else json.dumps(resolved)

            return re.sub(r"\$\{\{.*?\}\}", replace, value, flags=re.DOTALL)

        inputs = {key: render(str(value)) for key, value in step["with"].items()}
        policy = inputs.pop("policy")
        request = {
            key.replace("-", "_"): json.loads(value) if key in {"affected", "requested"} else value
            for key, value in inputs.items()
            if key != "output"
        }
        normalized = {
            "name": case["name"],
            "request": request,
            "expected": case.get("expected", []),
            "exit": case.get("exit", 0),
        }
        with tempfile.TemporaryDirectory() as directory:
            fixture = Path(directory) / "case.json"
            fixture.write_text(json.dumps([normalized]))
            verify(Path(policy), fixture)


if __name__ == "__main__":
    verify(Path(sys.argv[1]), Path(sys.argv[2]))
    if len(sys.argv) > 3 and sys.argv[3]:
        verify_workflows(Path(sys.argv[3]))
