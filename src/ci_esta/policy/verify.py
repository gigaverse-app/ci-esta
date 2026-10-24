"""Run project-owned routing examples through the installed CLI, without pytest.

Usage: python -m ci_esta.policy.verify POLICY CASES
Cases are a JSON list with name, request (CLI fields), affected and expected IDs.
This is a contract-test helper, never a substitute for test execution evidence.
"""

import json
import subprocess
import sys
import tempfile
from pathlib import Path


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


if __name__ == "__main__":
    verify(Path(sys.argv[1]), Path(sys.argv[2]))
