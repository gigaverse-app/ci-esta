"""
Command line interface for shared pytest timing utilities.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from pytest_selective.pytest_sharding import load_durations, merge_duration_files, plan_shards, write_shard_files
from pytest_selective.test_inventory import DEFAULT_TEST_FILE_PATTERNS

from ci_esta.testing.canary_run import (
    DEFAULT_COLLECT_TIMEOUT_SECONDS,
    DEFAULT_STAGE_BUDGET_SECONDS,
    prune_canary,
    run_canary,
)
from ci_esta.testing.coverage import read_coverage_summary
from ci_esta.testing.junit import (
    DEFAULT_CANARY_MAX_FILES,
    format_duration,
    format_failure_canary_summary,
    plan_failure_canary,
    summarize_junit_timings,
    write_failure_canary_file,
)
from ci_esta.testing.local_shards import LocalShardRunConfig, run_local_shards
from ci_esta.testing.runner_pools import plan_runner_pools


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    pools = commands.add_parser("pools", help="Assign global shard ranges to bounded runner pools")
    pools.add_argument("--shards", type=int, required=True)
    pools.add_argument("--shards-per-runner", type=int, required=True)
    pools.add_argument("--github-output", type=Path)

    plan = commands.add_parser("plan", help="Write duration-balanced pytest path shards")
    plan.add_argument("--durations", type=Path, default=Path(".test_durations"))
    plan.add_argument("--test-root", action="append", type=Path, default=[])
    plan.add_argument("--shards", type=int, required=True)
    plan.add_argument("--output-dir", type=Path, required=True)
    plan.add_argument("--threshold", type=float, default=50.0)
    plan.add_argument("--max-unit-tests", type=int, default=250)
    plan.add_argument("--max-unit-files", type=int, default=10)
    plan.add_argument("--unknown-test-file-duration", type=float, default=1.0)
    plan.add_argument("--exact-files", action="store_true")
    plan.add_argument("--test-file-pattern", action="append", default=[])

    local = commands.add_parser("run-local", help="Run independent shard commands concurrently on one runner")
    local.add_argument("--shards", type=int, required=True)
    local.add_argument("--first-shard", type=int, default=1)
    local.add_argument("--last-shard", type=int)
    local.add_argument("--log-dir", type=Path, required=True)
    local.add_argument("--success-tail-lines", type=int, default=20)
    local.add_argument("--failure-tail-lines", type=int, default=200)
    local.add_argument("--progress-interval-seconds", type=float, default=60)
    local.add_argument("shard_command", nargs=argparse.REMAINDER)

    merge = commands.add_parser("merge", help="Merge per-shard pytest duration manifests")
    merge.add_argument("input_files", nargs="+", type=Path)
    merge.add_argument("--output", "-o", type=Path, default=Path(".test_durations"))

    junit = commands.add_parser("junit", help="Summarize total and parallel JUnit time")
    junit.add_argument("junit_files", nargs="+", type=Path)

    canary = commands.add_parser("canary", help="Select whole files with terminal failures from prior JUnit reports")
    canary.add_argument("junit_files", nargs="+", type=Path)
    canary.add_argument("--output", "-o", type=Path, required=True)
    canary.add_argument("--max-files", type=int, default=DEFAULT_CANARY_MAX_FILES)
    canary.add_argument("--working-directory", type=Path, default=Path("."))

    canary_run = commands.add_parser(
        "canary-run",
        help="Run planned canary files, dropping files the full matrix would not run; pytest args go after `--`",
    )
    canary_run.add_argument("canary_file", type=Path)
    canary_run.add_argument("--collect-timeout", type=float, default=DEFAULT_COLLECT_TIMEOUT_SECONDS)
    canary_run.add_argument("--stage-budget", type=float, default=DEFAULT_STAGE_BUDGET_SECONDS)
    canary_run.add_argument("--prune-only", action="store_true")
    canary_run.add_argument("--output", type=Path, default=None)

    coverage = commands.add_parser("coverage", help="Validate an existing coverage.py XML report")
    coverage.add_argument("coverage_xml", type=Path)
    coverage.add_argument("--fail-under", type=float, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    """
    Run a timing utility subcommand.
    """
    raw_args = list(sys.argv[1:] if argv is None else argv)
    pytest_args: list[str] = []
    # argparse.REMAINDER cannot mix with subcommand options, so the pytest
    # argument tail after the first `--` is split off before parsing.
    if raw_args[:1] == ["canary-run"] and "--" in raw_args:
        separator = raw_args.index("--")
        raw_args, pytest_args = raw_args[:separator], raw_args[separator + 1 :]
    parser = _parser()
    args = parser.parse_args(raw_args)
    if args.command == "pools":
        try:
            pools = plan_runner_pools(args.shards, args.shards_per_runner)
        except ValueError as exc:
            parser.error(str(exc))
        payload = json.dumps([pool.model_dump() for pool in pools], separators=(",", ":"))
        if args.github_output:
            with args.github_output.open("a", encoding="utf-8") as output:
                output.write(f"count={len(pools)}\npools={payload}\n")
        print(payload)
        return 0
    if args.command == "canary-run":
        if args.output is not None and not args.prune_only:
            parser.error("--output requires --prune-only")
        if args.prune_only:
            return prune_canary(
                args.canary_file,
                pytest_args,
                collect_timeout_seconds=args.collect_timeout,
                stage_budget_seconds=args.stage_budget,
                output=args.output,
            )
        return run_canary(
            args.canary_file,
            pytest_args,
            collect_timeout_seconds=args.collect_timeout,
            stage_budget_seconds=args.stage_budget,
        )
    if args.command == "plan":
        shards = plan_shards(
            load_durations(args.durations),
            args.test_root or [Path("tests")],
            args.shards,
            threshold=args.threshold,
            max_unit_tests=args.max_unit_tests,
            max_unit_files=args.max_unit_files,
            unknown_test_file_duration=args.unknown_test_file_duration,
            exact_files=args.exact_files,
            test_file_patterns=tuple(args.test_file_pattern) or DEFAULT_TEST_FILE_PATTERNS,
        )
        write_shard_files(shards, args.output_dir)
        for index, shard in enumerate(shards, start=1):
            print(f"shard={index} duration={shard.duration:.1f}s tests={shard.count} paths={len(shard.paths)}")
        total = sum(shard.duration for shard in shards)
        slowest = max((shard.duration for shard in shards), default=0.0)
        print(f"total={total:.1f}s slowest={slowest:.1f}s")
        return 0
    if args.command == "run-local":
        command = list(args.shard_command)
        if command[:1] == ["--"]:
            command = command[1:]
        if not command:
            parser.error("run-local requires a command after --")
        return run_local_shards(
            LocalShardRunConfig(
                shard_count=args.shards,
                first_shard=args.first_shard,
                last_shard=args.last_shard,
                command=command,
                log_dir=args.log_dir,
                success_tail_lines=args.success_tail_lines,
                failure_tail_lines=args.failure_tail_lines,
                progress_interval_seconds=args.progress_interval_seconds,
            )
        )
    if args.command == "merge":
        merged = merge_duration_files(args.input_files, args.output)
        print(f"merged_tests={len(merged)}")
        return 0

    if args.command == "junit":
        timings = summarize_junit_timings(args.junit_files)
        print(f"total_test_time={format_duration(timings.total_seconds)}")
        print(f"wall_time={format_duration(timings.wall_seconds)}")
        return 0

    if args.command == "canary":
        plan = plan_failure_canary(
            args.junit_files,
            max_files=args.max_files,
            working_directory=args.working_directory,
        )
        write_failure_canary_file(plan, args.output)
        print(format_failure_canary_summary(plan))
        return 0

    summary = read_coverage_summary(args.coverage_xml)
    print(f"coverage_percent={summary.percent:.2f}")
    if summary.meets(args.fail_under):
        return 0
    print(f"coverage {summary.percent:.2f}% is below required {args.fail_under:.2f}%")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
