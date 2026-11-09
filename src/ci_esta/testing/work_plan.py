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
import subprocess
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
        for reason, lanes in python_entry_lanes(repo, config, base, head, (before, after), set(result.changed)).items():
            reasons.setdefault(reason, set()).update(lanes)
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


def python_entry_lanes(
    repo: Path, config: LaneConfig, base: str, head: str, graphs: tuple[WorkflowGraph, ...], changed: set[str]
) -> dict[str, set[str]]:
    """Lanes of the jobs whose Python entry points import a changed file, through pytest-selective's graph.

    A job that runs `python -m pkg.tool`, a console script or `python scripts/x.py` depends on what that
    module imports, not on the whole package: a change outside the import closure leaves the job alone.
    """
    from pytest_selective.ast_imports import normalized_name
    from pytest_selective.impact_graph import GraphCache, ModuleIndex, reachable, reverse_edges, seed_nodes, union_edges
    from pytest_selective.impact_models import contents_node

    jobs = [
        (f"{path}#{name}", job)
        for graph in graphs
        for (path, name), job in graph.jobs.items()
        if job.lanes and ALL not in job.lanes and (job.modules or any(item.endswith(".py") for item in job.inputs))
    ]
    if not jobs or not changed:
        return {}
    cache = GraphCache(repo / ".test-impact/cache.sqlite3")
    try:
        snapshots = [cache.snapshot(repo, revision, config.graph) for revision in (base, head)]
    finally:
        cache.close()
    edges = union_edges(*snapshots)
    impacted = reachable(reverse_edges(edges), seed_nodes(sorted(changed)))
    index = ModuleIndex(
        {path for snapshot in snapshots for path in snapshot.files if path.endswith(".py")},
        config.graph.module_roots,
        [],
    )
    reasons: dict[str, set[str]] = {}
    for label, job in jobs:
        # A name counts only when it is a module of this repository, not a prefix of one or an attribute path.
        modules = {
            path
            for module in job.modules
            for name in (module, f"{module}.__main__")
            if normalized_name(name) in index.modules
            for path in index.resolve(name)
        }
        # A changed file the job names is a workflow input already; here only what reaches it by import counts.
        entries = (modules | {path for path in job.inputs if path.endswith(".py")}) - changed
        for entry in sorted(entries & impacted):
            closure = reachable(edges, {entry})
            via = sorted(path for path in changed if path in closure or contents_node(path) in closure)
            if via:
                reasons.setdefault(f"workflow input: {via[0]} reaches {entry} (run by {label})", set()).update(
                    job.lanes
                )
                break
    return reasons


def commit_exists(repo: Path, revision: str) -> bool:
    return (
        subprocess.run(
            ["git", "-C", str(repo), "cat-file", "-e", f"{revision}^{{commit}}"], capture_output=True
        ).returncode
        == 0
    )


def tested_base(repo: Path, base: str, head: str, pr_head: str) -> str:
    """The base GitHub's merge of the pull request was built on, as pytest-selective's planner uses.

    A pull request's `base.sha` can be older than the base-branch tip GitHub merged it into, so commits
    that landed since would read as the PR's own. pytest-selective owns that rule
    (`pull_request_merge_base`, from 1.3.0); with an older pytest-selective, `base` is kept, which only
    plans more lanes, never fewer.
    """
    try:
        from pytest_selective.git_operations import pull_request_merge_base
    except ImportError:
        return base
    tested = pull_request_merge_base(repo, base, head, pr_head)
    if tested != base:
        print(
            f"Planning against the tested merge's base {tested}; the event's base {base} is behind it.", file=sys.stderr
        )
    return tested


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
    parser.add_argument("--base", required=True, help="base commit; empty or all zeros runs every lane")
    parser.add_argument("--head", default="HEAD")
    # A pull request's head: when `--head` is GitHub's merge of it, plan against the merge's actual base.
    parser.add_argument("--pr-head", default="")
    parser.add_argument(
        "--full", nargs="?", const="true", default="false", type=full_checkpoint_reason, metavar="auto|true|false"
    )
    parser.add_argument("--github-output", type=Path)
    parser.add_argument("--bun", default="bun", help="Bun executable, for repositories with Bun tests")
    parser.add_argument("--summary", type=Path, help="append a readable table of the plan (step summary)")
    args = parser.parse_args(argv)
    if not args.base.strip("0"):
        # A branch's first push has no `before` (all zeros), and some callers pass nothing: compare against
        # nothing, and run every lane.
        args.full, args.base = "full run: no base commit to compare against", args.head
    elif not commit_exists(args.repo, args.base):
        # A shallow checkout or a force-pushed `before`: nothing to compare against, so every lane runs.
        args.full, args.base = f"full run: base commit {args.base} is not in this checkout's history", args.head
    else:
        args.base = tested_base(args.repo, args.base, args.head, args.pr_head)
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
