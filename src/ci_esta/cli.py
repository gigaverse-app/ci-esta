"""Collect GitHub Actions timing evidence or render an existing report locally."""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from ci_esta.ci_observability.action import ActionConfig, run
from ci_esta.ci_observability.models import ActionsJobGateSelectorV1, CiObservabilityReportV1, GateKind
from ci_esta.ci_observability.report import render_markdown, render_prometheus
from ci_esta.extras import requires_selection

TOKEN_HELP = (
    "ci-esta report: no GitHub token. Set GH_TOKEN or GITHUB_TOKEN to a token that can read the repository's "
    "Actions runs (actions: read, contents: read; checks: read for gates).\n"
    "With the GitHub CLI signed in: export GH_TOKEN=\"$(gh auth token)\"\n"
    "The token is read from the environment only; it is never accepted as an argument or printed."
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="CI-esta: GitHub Actions timing, cost estimates and evidence")
    commands = parser.add_subparsers(dest="command", required=True)
    adoption = commands.add_parser("adoption", help="Read-only adoption inventory and suggestions; never changes CI")
    adoption.add_argument("--root", type=Path, default=Path("."))
    adoption.add_argument("--json", action="store_true")
    adoption.add_argument("--ignore", action="append", default=[], metavar="SUGGESTION_ID")
    audit = commands.add_parser("check-workflow", help="Validate selected-lane aggregate gate wiring")
    audit.add_argument("--workflow", type=Path, required=True)
    audit.add_argument("--lanes", type=Path, help="lane file; omitted, lanes are inferred from the workflows")
    audit.add_argument("--repo", type=Path, default=Path("."))
    audit.add_argument("--gate", default="Validation gate",
                       help="The aggregate job's exact name; keep an existing required check's name")
    collect = commands.add_parser("report", help="Read a GitHub Actions run and save JSON, Markdown and Prometheus")
    collect.add_argument("--repository", required=True, help="owner/repository")
    collect.add_argument("--run-id", required=True, type=int)
    collect.add_argument("--run-attempt", type=int, default=1)
    collect.add_argument("--commit-sha", default="")
    collect.add_argument("--gate", action="append", default=[], help="Exact required job name; repeat for multiple gates")
    collect.add_argument("--critical-path", action="store_true", help="Analyze source workflow dependencies as data")
    collect.add_argument("--output-dir", type=Path, default=Path("ci-esta-report"))
    collect.add_argument("--api-url", default="https://api.github.com")
    render = commands.add_parser("render", help="Render a saved JSON report without network access")
    render.add_argument("report", type=Path)
    render.add_argument("--markdown", required=True, type=Path)
    render.add_argument("--prometheus", required=True, type=Path)
    commands.add_parser(
        "lanes", add_help=False, help="Show the lanes, where each came from, and why a plan runs or skips them"
    )
    commands.add_parser("checkpoint", add_help=False, help="Install or dispatch scheduled full-validation workflows")
    if argv is None:
        argv = sys.argv[1:]
    if argv[:1] == ["checkpoint"]:
        from ci_esta.checkpoint import main as checkpoint

        return checkpoint(argv[1:])
    if argv[:1] == ["lanes"]:
        with requires_selection("ci-esta lanes"):
            from ci_esta.testing.lane_report import main as lanes

            return lanes(argv[1:])
    args = parser.parse_args(argv)
    if args.command == "adoption":
        from ci_esta.adoption import inspect
        from ci_esta.adoption import render as render_adoption
        report = inspect(args.root, ignore=set(args.ignore))
        print(report.model_dump_json(indent=2) if args.json else render_adoption(report))
        return 0
    if args.command == "check-workflow":
        try:
            with requires_selection("ci-esta check-workflow"):
                from ci_esta.testing.workflow_adoption import check
                check(args.workflow, args.lanes, args.repo, args.gate)
        except ValueError as error:
            print(f"{args.workflow}: {error}", file=sys.stderr)
            return 2
        print("Workflow lane and aggregate-gate contracts passed")
        return 0
    if args.command == "render":
        report = CiObservabilityReportV1.model_validate_json(args.report.read_bytes())
        for path, content in ((args.markdown, render_markdown(report)), (args.prometheus, render_prometheus(report))):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
        return 0
    # Credentials stay in environment/process memory; the CLI never accepts or prints a token.
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN", "")
    if not token:
        print(TOKEN_HELP, file=sys.stderr)
        return 2
    return run(ActionConfig(
        repository=args.repository, github_token=token, api_url=args.api_url,
        run_id=args.run_id, run_attempt=args.run_attempt, commit_sha=args.commit_sha,
        pull_request_number=None,
        gate_selectors=[ActionsJobGateSelectorV1(kind=GateKind.ACTIONS_JOB, job_name=name) for name in args.gate],
        repository_signals=[], extensions={},
        report_output=args.output_dir / "ci-observability.json",
        markdown_output=args.output_dir / "ci-observability.md",
        prometheus_output=args.output_dir / "ci-observability.prom",
        post_sticky=False, append_summary=False,
        analyze_critical_path=args.critical_path,
    ), datetime.now(timezone.utc))


if __name__ == "__main__":
    raise SystemExit(main())
