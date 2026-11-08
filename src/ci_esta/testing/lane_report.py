"""Show which lanes exist, where each came from, and why a plan ran or skipped it."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from pytest_selective.ci import LanePlan

from ci_esta.testing.lane_inference import EXTENDS, ResolvedLanes, resolve


def cell(values: list[str], limit: int = 4) -> str:
    shown = [value.replace("|", "\\|") for value in values[:limit]]
    if len(values) > limit:
        shown.append(f"… {len(values) - limit} more")
    return "<br>".join(shown) or "–"


def render(resolved: ResolvedLanes, plan: LanePlan | None = None) -> str:
    """A Markdown table: one row per lane, with its roots, jobs, origin and, given a plan, the decision."""
    header = ["Lane", "Tests (roots)", "Jobs it gates", "Defined by"]
    if plan is not None:
        header = ["Lane", "Runs", "Why", *header[1:]]
    rows = ["| " + " | ".join(header) + " |", "|" + " --- |" * len(header)]
    for name, lane in resolved.config.lanes.items():
        jobs = [job.split("#", 1)[1] if "#" in job else job for job in resolved.jobs.get(name, [])]
        facts = [cell(lane.roots), cell(jobs), cell(resolved.sources.get(name, []), 2)]
        if plan is not None:
            runs = "✅ runs" if plan.lanes.get(name) else "⏭️ skipped"
            facts = [runs, cell(plan.lane_reasons.get(name, []), 3), *facts]
        rows.append(f"| `{name}` | " + " | ".join(facts) + " |")
    lines = rows
    if plan is not None:
        lines = [f"**Plan:** {plan.reason}", "", *rows]
    return "\n".join(lines) + "\n"


def template(resolved: ResolvedLanes) -> dict[str, object]:
    """A lane file that extends the workflow, starting from what was inferred: delete what you keep."""
    return {
        EXTENDS: "workflow",
        "lanes": {name: lane.model_dump(exclude_defaults=True) for name, lane in resolved.config.lanes.items()},
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ci-esta lanes", description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path("."))
    parser.add_argument("--config", type=Path, help="lane file; omitted, lanes are inferred from the workflows")
    parser.add_argument("--base", help="explain a plan from this commit to --head")
    parser.add_argument("--head", default="HEAD")
    parser.add_argument("--write", type=Path, help="save the lanes as a lane file that extends the workflow")
    parser.add_argument("--json", action="store_true", help="print the resolved lanes as JSON")
    args = parser.parse_args(argv)
    resolved = resolve(args.repo, args.base or args.head, args.head, args.config)
    if args.write:
        args.write.parent.mkdir(parents=True, exist_ok=True)
        args.write.write_text(json.dumps(template(resolved), indent=2) + "\n", encoding="utf-8")
        print(f"Wrote {args.write}: delete the lanes the workflow already gets right, edit the rest.", file=sys.stderr)
    plan = None
    if args.base:
        from ci_esta.testing.work_plan import plan_work

        plan = plan_work(args.repo, resolved.config, args.base, args.head)
    if args.json:
        payload = resolved.model_dump(mode="json")
        if plan is not None:
            payload["plan"] = plan.model_dump(mode="json")
        print(json.dumps(payload, indent=2))
    else:
        print(render(resolved, plan), end="")
    return 0
