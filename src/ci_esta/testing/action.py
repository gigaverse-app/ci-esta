"""
GitHub Action adapter for shared pytest artifact aggregation.
"""

from __future__ import annotations

import os
from pathlib import Path

from pydantic import BaseModel, ConfigDict, model_validator
from pytest_selective.pytest_sharding import merge_duration_files

from ci_esta.testing.artifacts import matching_artifacts
from ci_esta.testing.coverage import read_coverage_summary
from ci_esta.testing.junit import format_duration, summarize_junit_timings


class AggregationConfig(BaseModel):
    """
    Consumer-provided artifact layout and validation policy.
    """

    model_config = ConfigDict(frozen=True)

    artifact_directory: Path
    duration_pattern: str
    junit_pattern: str
    shard_count: int
    duration_output: Path
    coverage_xml: Path | None = None
    coverage_fail_under: float | None = None

    @model_validator(mode="after")
    def validate_coverage_pair(self) -> "AggregationConfig":
        if (self.coverage_xml is None) != (self.coverage_fail_under is None):
            raise ValueError("coverage_xml and coverage_fail_under must be provided together")
        if self.shard_count < 1:
            raise ValueError("shard_count must be at least 1")
        return self


class AggregationResult(BaseModel):
    """
    Stable outputs consumed by repository-specific workflow steps.
    """

    model_config = ConfigDict(frozen=True)

    merged_tests: int
    total_test_time: str
    wall_time: str
    coverage_percent: float | None = None


def aggregate_artifacts(config: AggregationConfig) -> AggregationResult:
    """
    Merge duration manifests, summarize JUnit time, and optionally enforce coverage.
    """
    duration_files = matching_artifacts(
        config.artifact_directory,
        config.duration_pattern,
        config.shard_count,
        "duration",
    )
    junit_files = matching_artifacts(
        config.artifact_directory,
        config.junit_pattern,
        config.shard_count,
        "JUnit",
    )
    config.duration_output.parent.mkdir(parents=True, exist_ok=True)
    merged = merge_duration_files(duration_files, config.duration_output)
    timings = summarize_junit_timings(junit_files)

    coverage_percent: float | None = None
    if config.coverage_xml is not None and config.coverage_fail_under is not None:
        coverage = read_coverage_summary(config.coverage_xml)
        if not coverage.meets(config.coverage_fail_under):
            raise ValueError(f"coverage {coverage.percent:.2f}% is below required {config.coverage_fail_under:.2f}%")
        coverage_percent = coverage.percent

    return AggregationResult(
        merged_tests=len(merged),
        total_test_time=format_duration(timings.total_seconds),
        wall_time=format_duration(timings.wall_seconds),
        coverage_percent=coverage_percent,
    )


def _optional_path(value: str) -> Path | None:
    return Path(value) if value else None


def _optional_float(value: str) -> float | None:
    return float(value) if value else None


def _append_action_outputs(result: AggregationResult) -> None:
    output_path = os.environ.get("GITHUB_OUTPUT")
    if output_path:
        coverage_percent = "" if result.coverage_percent is None else f"{result.coverage_percent:.2f}"
        with Path(output_path).open("a") as output:
            output.write(f"merged_tests={result.merged_tests}\n")
            output.write(f"total_test_time={result.total_test_time}\n")
            output.write(f"wall_time={result.wall_time}\n")
            output.write(f"coverage_percent={coverage_percent}\n")

    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with Path(summary_path).open("a") as summary:
            summary.write(f"Total test time: {result.total_test_time}  \n")
            summary.write(f"Parallel wall time: {result.wall_time}\n")


def main() -> int:
    """
    Aggregate artifacts using composite-action inputs from the environment.
    """
    config = AggregationConfig(
        artifact_directory=Path(os.environ["INPUT_ARTIFACT_DIRECTORY"]),
        duration_pattern=os.environ["INPUT_DURATION_PATTERN"],
        junit_pattern=os.environ["INPUT_JUNIT_PATTERN"],
        shard_count=int(os.environ["INPUT_SHARD_COUNT"]),
        duration_output=Path(os.environ["INPUT_DURATION_OUTPUT"]),
        coverage_xml=_optional_path(os.environ.get("INPUT_COVERAGE_XML", "")),
        coverage_fail_under=_optional_float(os.environ.get("INPUT_COVERAGE_FAIL_UNDER", "")),
    )
    result = aggregate_artifacts(config)
    _append_action_outputs(result)
    print(f"merged_tests={result.merged_tests}")
    print(f"total_test_time={result.total_test_time}")
    print(f"wall_time={result.wall_time}")
    if result.coverage_percent is not None:
        print(f"coverage_percent={result.coverage_percent:.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
