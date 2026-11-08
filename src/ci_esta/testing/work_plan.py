"""Plan complete lanes from the language selector and CI-esta's workflow graph.

pytest-selective decides which Python tests a change affects. The workflow graph decides which
lanes a change to CI reaches: a changed job selects the lanes its conditions read, a changed file
selects the lanes of the jobs that execute it, and the planner job reaches every lane. With the
built-in input policy, nothing under `.github/` is a global input any more: a pull-request template
or an unused helper selects nothing. Explicit `global_inputs` in the lane file are kept exactly.

The output is pytest-selective's `LanePlan`, so lane conditions, the validation gate and the
CI-esta report read it unchanged.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from pytest_selective.checkpoint import full_checkpoint_reason
from pytest_selective.ci import LaneConfig, LanePlan, plan
from pytest_selective.impact_graph import DependencyDeclarationError
from pytest_selective.input_policy import DEFAULT_GLOBAL_INPUTS

from ci_esta.package_inputs import PackageInputsUnavailable, changed_package_inputs
from ci_esta.testing.bun.graph import bun_lane_reasons
from ci_esta.testing.lane_inference import resolve
from ci_esta.testing.lane_report import render
from ci_esta.testing.lane_rules import BUN_ENVIRONMENT, PYTHON_ENVIRONMENT, Rule, by_name, effective
from ci_esta.workflow_graph import ALL, WorkflowGraph, changed_job_lanes


def plan_work(
    repo: Path,
    config: LaneConfig,
    base: str,
    head: str,
    *,
    full: bool = False,
    bun: str = "bun",
    rules: list[Rule] | None = None,
) -> LanePlan:
    """pytest-selective's lane plan, with CI changes routed through the workflow graph.

    `rules` are the rules in force (`ci-esta lanes` lists them); None keeps the built-in defaults.
    """
    rules = effective([], []) if rules is None else rules
    python = by_name(rules, PYTHON_ENVIRONMENT)
    if python is None or python.origin != "built-in":
        # A replaced or disabled Python environment rule decides what is global, for the graph too.
        patterns = python.when if python is not None and python.select == ["all"] else []
        graph = config.graph.model_copy(update={"global_inputs": patterns})
        config = config.model_copy(update={"graph": graph, "global_inputs": patterns})
    bun_rule = by_name(rules, BUN_ENVIRONMENT)
    bun_environment = bun_rule.when if bun_rule is not None and bun_rule.select == ["bun"] else None
    generic = [
        rule
        for rule in rules
        if (rule.name, tuple(rule.select)) not in {(PYTHON_ENVIRONMENT, ("all",)), (BUN_ENVIRONMENT, ("bun",))}
    ]
    if config.global_inputs is None:
        # The selector's built-in policy treats non-Markdown .github/ files as global inputs because
        # it cannot see workflows. The workflow graph can, so keep only the environment defaults.
        config = config.model_copy(update={"global_inputs": list(DEFAULT_GLOBAL_INPUTS)})
    result = plan(repo, config, base, head, full=full)
    if full or not result.changed or result.reason.startswith("full-suite fallback"):
        return result
    try:
        before, after = WorkflowGraph(repo, base), WorkflowGraph(repo, head)
        reasons = changed_job_lanes(before, after, set(result.changed))
    except DependencyDeclarationError:
        # An authoring error to fix, as pytest-selective treats it, never a silent full run.
        raise
    except Exception as error:  # noqa: BLE001 - an unreadable workflow must run work, never skip it
        reason = f"full-suite fallback: workflow graph unavailable: {error}"
        return result.model_copy(
            update={
                "lanes": dict.fromkeys(config.lanes, True),
                "reason": reason,
                "lane_reasons": {name: [reason] for name in config.lanes},
            }
        )
    # Bun tests reach lanes through Bun's own module graph, built from the checked-out head.
    roots = {name: lane.roots for name, lane in config.lanes.items()}
    bun_reasons = bun_lane_reasons(repo, roots, set(result.changed), bun, bun_environment)
    # A job that builds the package runs when the package's inputs change, as the build tools list them.
    package_lanes = after.package_lanes()
    if package_lanes - {lane for lane, selected in result.lanes.items() if selected}:
        try:
            found = changed_package_inputs(repo, after.files, set(result.changed))
        except (PackageInputsUnavailable, ValueError, OSError) as error:
            found = [f"full-suite fallback: package inputs unavailable: {error}"]
        for reason in found:
            reasons[reason] = package_lanes
    for rule in generic:
        for path in rule.fired_by(set(result.changed)):
            reasons[f"rule {rule.name}: {path}" + (f" ({rule.reason})" if rule.reason else "")] = targets(
                rule, after, package_lanes, set(bun_reasons)
            )
    lanes = dict(result.lanes)
    evidence = {
        name: [
            value.replace("global input: ", f"rule {PYTHON_ENVIRONMENT}: ", 1) if python is not None else value
            for value in values
        ]
        for name, values in result.lane_reasons.items()
    }
    for name in config.lanes:
        added = [reason for reason, selected in reasons.items() if ALL in selected or name in selected]
        added += bun_reasons.get(name, [])
        if added:
            if not lanes[name]:
                evidence[name] = []
            lanes[name] = True
            evidence[name].extend(added)
    return result.model_copy(update={"lanes": lanes, "lane_reasons": evidence})


def targets(rule: Rule, graph: WorkflowGraph, package_lanes: set[str], bun_lanes: set[str]) -> set[str]:
    """The lanes a rule selects."""
    selected: set[str] = set()
    for value in rule.select:
        if value == "all":
            selected.add(ALL)
        elif value == "package":
            selected |= package_lanes
        elif value == "bun":
            selected |= bun_lanes
        elif value.startswith("lane:"):
            selected.add(value.removeprefix("lane:"))
        else:
            workflow, _, job = value.removeprefix("job:").partition("#")
            if (workflow, job) not in graph.jobs:
                raise ValueError(f"rule {rule.name}: {workflow} has no job {job!r}")
            selected |= graph.jobs[(workflow, job)].lanes
    return selected


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, help="lane file; omitted, lanes are inferred from the workflows")
    parser.add_argument("--repo", type=Path, default=Path("."))
    parser.add_argument("--base", required=True)
    parser.add_argument("--head", default="HEAD")
    parser.add_argument(
        "--full", nargs="?", const="true", default="false", type=full_checkpoint_reason, metavar="auto|true|false"
    )
    parser.add_argument("--github-output", type=Path)
    parser.add_argument("--bun", default="bun", help="Bun executable, for repositories with Bun tests")
    parser.add_argument("--summary", type=Path, help="append a readable table of the plan (step summary)")
    args = parser.parse_args(argv)
    try:
        resolved = resolve(args.repo, args.base, args.head, args.config)
        config = resolved.config
        result = plan_work(
            args.repo, config, args.base, args.head, full=args.full is not None, bun=args.bun, rules=resolved.rules
        )
        if args.full is not None:
            result.reason = args.full
    except (ValueError, OSError, DependencyDeclarationError) as error:
        print(f"Invalid lane configuration/dependency: {error}", file=sys.stderr)
        return 2
    print(result.model_dump_json(indent=2))
    if args.summary:
        with args.summary.open("a", encoding="utf-8") as summary:
            summary.write("### Lane selection\n\n" + render(resolved, result) + "\n")
    if args.github_output:
        with args.github_output.open("a", encoding="utf-8") as output:
            for name, enabled in result.lanes.items():
                output.write(f"{name}={str(enabled).lower()}\n")
            output.write(f"lanes={json.dumps(result.lanes)}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
