"""Collect GitHub Actions timing evidence or render an existing report locally."""

import argparse
import os
from datetime import datetime, timezone
from pathlib import Path

from ci_esta.ci_observability.action import ActionConfig, run
from ci_esta.ci_observability.models import ActionsJobGateSelectorV1, CiObservabilityReportV1, GateKind
from ci_esta.ci_observability.report import render_markdown, render_prometheus


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="CI-esta: GitHub Actions timing, cost estimates and evidence")
    commands = parser.add_subparsers(dest="command", required=True)
    collect = commands.add_parser("report", help="Read a GitHub Actions run and save JSON, Markdown and Prometheus")
    collect.add_argument("--repository", required=True, help="owner/repository")
    collect.add_argument("--run-id", required=True, type=int)
    collect.add_argument("--run-attempt", type=int, default=1)
    collect.add_argument("--commit-sha", default="")
    collect.add_argument("--gate", action="append", default=[], help="Exact required job name; repeat for multiple gates")
    collect.add_argument("--output-dir", type=Path, default=Path("ci-esta-report"))
    collect.add_argument("--api-url", default="https://api.github.com")
    render = commands.add_parser("render", help="Render a saved JSON report without network access")
    render.add_argument("report", type=Path)
    render.add_argument("--markdown", required=True, type=Path)
    render.add_argument("--prometheus", required=True, type=Path)
    args = parser.parse_args(argv)
    if args.command == "render":
        report = CiObservabilityReportV1.model_validate_json(args.report.read_bytes())
        for path, content in ((args.markdown, render_markdown(report)), (args.prometheus, render_prometheus(report))):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
        return 0
    # Credentials stay in environment/process memory; the CLI never accepts or prints a token.
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN", "")
    if not token:
        parser.error("Set GITHUB_TOKEN or GH_TOKEN with read access to the repository's Actions runs")
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
    ), datetime.now(timezone.utc))


if __name__ == "__main__":
    raise SystemExit(main())
