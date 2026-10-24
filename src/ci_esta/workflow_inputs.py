"""Compare execution inputs and consume complete-range selector evidence.

This is workflow configuration projection, not an application dependency graph.
Callers own lane/job mappings and source-path admission. A failed proof runs work.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml


def workflow_inputs(document: dict[str, Any], lane: str) -> dict[str, Any]:
    """Keep a job, workflow settings, and prerequisites supplying execution data.

    Conditions/names do not consume prerequisite execution data. The selected job's
    full definition still participates, including its own conditions. Any reference
    to ``needs`` in execution data conservatively includes every declared prerequisite,
    covering bracket syntax and toJSON(needs) without an expression interpreter.
    """
    jobs = document["jobs"]
    selected = {}
    pending = [lane]
    while pending:
        name = pending.pop()
        if name in selected:
            continue
        if name not in jobs:
            raise ValueError(f"Unknown prerequisite: {name}")
        job = jobs[name]
        selected[name] = job
        needs = job.get("needs", [])
        if isinstance(needs, str):
            needs = [needs]
        if not isinstance(needs, list) or any(not isinstance(item, str) for item in needs):
            raise ValueError(f"Invalid prerequisites: {name}")
        execution = {key: value for key, value in job.items() if key not in {"if", "needs", "name", "steps"}}
        execution["steps"] = [
            {key: value for key, value in step.items() if key not in {"if", "name"}} for step in job.get("steps", [])
        ]
        if re.search(r"\bneeds\b", json.dumps(execution)):
            pending.extend(needs)
    return {**{key: value for key, value in document.items() if key != "jobs"}, "jobs": selected}


def git(*args: str) -> str:
    return subprocess.run(["git", *args], check=True, capture_output=True, text=True).stdout.strip()


def changed_lanes(
    base: str, head: str, *, workflow: str, lanes: dict[str, str], merge_base: str | None = None
) -> dict[str, bool]:
    """Compare the complete range, optionally retaining a pre-shallow-fetch base."""
    merge_base = merge_base or git("merge-base", base, head)
    before = yaml.safe_load(git("show", f"{merge_base}:{workflow}"))
    after = yaml.safe_load(git("show", f"{head}:{workflow}"))
    return {key: workflow_inputs(before, lane) != workflow_inputs(after, lane) for key, lane in lanes.items()}


def selection_proof(report: Any, *, base_tree: str, head_tree: str, tests: dict[str, list[str]]) -> dict[str, bool]:
    """Consume a pytest-selective report; never recompute its application graph.

    Test groups contain exact selector IDs, not glob patterns. All members must be
    unaffected. Empty groups cannot establish proof. Full/fallback or incremental
    reports cannot discharge any complete-range source/dependency trigger.
    """
    unknown = {"dependencies-unchanged": False, **{f"{name}-unaffected": False for name in tests}}
    if not isinstance(report, dict) or report.get("base") != base_tree or report.get("head") != head_tree:
        return unknown
    if report.get("mode") not in {"scoped", "none"}:
        return unknown
    selected = report.get("selected")
    if not isinstance(selected, list) or any(not isinstance(path, str) for path in selected):
        return unknown
    return {
        "dependencies-unchanged": report.get("dependencies_unchanged") is True,
        **{
            f"{name}-unaffected": bool(paths) and not set(paths).intersection(selected) for name, paths in tests.items()
        },
    }


def dependency_proof(
    base: str, head: str, report_path: Path, *, tests: dict[str, list[str]], merge_base: str | None = None
) -> dict[str, bool]:
    merge_base = merge_base or git("merge-base", base, head)
    return selection_proof(
        json.loads(report_path.read_text()),
        base_tree=git("rev-parse", f"{merge_base}^{{tree}}"),
        head_tree=git("rev-parse", f"{head}^{{tree}}"),
        tests=tests,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workflow", required=True)
    parser.add_argument("--lanes", required=True, type=json.loads, help="JSON output-key to workflow-job mapping")
    parser.add_argument("--tests", default={}, type=json.loads, help="JSON group to exact selector test IDs")
    parser.add_argument("--base", required=True)
    parser.add_argument("--head", default="HEAD")
    parser.add_argument("--merge-base", help="Complete range base captured before incremental shallow fetches")
    parser.add_argument("--report", type=Path, default=Path("test-impact-report.json"))
    args = parser.parse_args()
    if (
        not isinstance(args.lanes, dict)
        or not args.lanes
        or any(
            not re.fullmatch(r"[a-zA-Z0-9_-]+", key) or not isinstance(value, str) or not value
            for key, value in args.lanes.items()
        )
    ):
        parser.error("--lanes must map nonempty output keys to job IDs")
    if not isinstance(args.tests, dict) or any(
        not re.fullmatch(r"[a-zA-Z0-9_-]+", key)
        or not isinstance(paths, list)
        or any(not isinstance(path, str) or not path for path in paths)
        for key, paths in args.tests.items()
    ):
        parser.error("--tests must map group names to lists of exact test IDs")
    proof_keys = {"dependencies-unchanged", *(f"{name}-unaffected" for name in args.tests)}
    if proof_keys.intersection(args.lanes):
        parser.error("Lane output keys must not collide with proof output keys")
    try:
        changed = changed_lanes(
            args.base, args.head, workflow=args.workflow, lanes=args.lanes, merge_base=args.merge_base
        )
    except (subprocess.CalledProcessError, yaml.YAMLError, KeyError, TypeError, ValueError, AttributeError):
        print("::warning::Cannot prove workflow inputs unchanged; running all independent lanes.", file=sys.stderr)
        changed = dict.fromkeys(args.lanes, True)
    try:
        proof = dependency_proof(args.base, args.head, args.report, tests=args.tests, merge_base=args.merge_base)
    except (OSError, subprocess.CalledProcessError, KeyError, TypeError, ValueError):
        proof = dict.fromkeys(proof_keys, False)
    for key, value in (changed | proof).items():
        print(f"{key}={str(value).lower()}")


if __name__ == "__main__":
    main()
