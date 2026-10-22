"""
GitHub Action adapter for planning a pytest previous-failure canary.
"""

from __future__ import annotations

import os
from collections import Counter
from pathlib import Path

from pydantic import BaseModel, ConfigDict, model_validator

from ci_esta.testing.artifacts import find_artifacts
from ci_esta.testing.junit import (
    DEFAULT_CANARY_MAX_FILES,
    PytestFailureCanaryPlan,
    format_failure_canary_summary,
    plan_failure_canary,
    write_failure_canary_file,
)


class CanaryConfig(BaseModel):
    """
    Consumer-provided prior-run artifact layout and canary bound.
    """

    model_config = ConfigDict(frozen=True)

    artifact_directory: Path
    junit_pattern: str
    junit_name_template: str = "junit-group-{shard}.xml"
    shard_count: int
    output: Path
    max_files: int = DEFAULT_CANARY_MAX_FILES
    working_directory: Path = Path(".")

    @model_validator(mode="after")
    def validate_bounds(self) -> "CanaryConfig":
        if self.shard_count < 1:
            raise ValueError("shard_count must be at least 1")
        if self.max_files < 1:
            raise ValueError("max_files must be at least 1")
        remainder = self.junit_name_template.replace("{shard}", "", 1)
        if (
            self.junit_name_template.count("{shard}") != 1
            or "{" in remainder
            or "}" in remainder
            or "/" in self.junit_name_template
            or "\\" in self.junit_name_template
        ):
            raise ValueError("junit_name_template must contain exactly one {shard} placeholder")
        return self


class CanaryActionResult(PytestFailureCanaryPlan):
    """
    Stable planner outputs consumed by a repository-specific workflow.
    """

    model_config = ConfigDict(frozen=True)

    distinct_shard_count: int
    artifacts_complete: bool


def build_canary(config: CanaryConfig) -> CanaryActionResult:
    """
    Build a canary from available reports and expose their completeness.
    """
    junit_files = find_artifacts(config.artifact_directory, config.junit_pattern)
    plan = plan_failure_canary(
        junit_files,
        max_files=config.max_files,
        working_directory=config.working_directory,
    )
    write_failure_canary_file(plan, config.output)
    expected_names = Counter(
        config.junit_name_template.format(shard=shard) for shard in range(1, config.shard_count + 1)
    )
    actual_names = Counter(path.name for path in junit_files)
    distinct_shard_count = len(set(actual_names) & set(expected_names))
    return CanaryActionResult(
        **plan.model_dump(exclude_computed_fields=True),
        distinct_shard_count=distinct_shard_count,
        # Enforcement point: completeness means every expected identity occurs
        # exactly once and every discovered report parsed as JUnit.
        artifacts_complete=actual_names == expected_names and plan.invalid_report_count == 0,
    )


def _append_action_outputs(config: CanaryConfig, result: CanaryActionResult) -> None:
    output_path = os.environ.get("GITHUB_OUTPUT")
    if not output_path:
        return
    with Path(output_path).open("a") as output:
        output.write(f"canary_file={config.output}\n")
        for name, value in result.model_dump(exclude={"selected_files"}).items():
            rendered = str(value).lower() if isinstance(value, bool) else value
            output.write(f"{name}={rendered}\n")


def main() -> int:
    """
    Plan a canary using composite-action inputs from the environment.
    """
    config = CanaryConfig(
        artifact_directory=Path(os.environ["INPUT_ARTIFACT_DIRECTORY"]),
        junit_pattern=os.environ["INPUT_JUNIT_PATTERN"],
        junit_name_template=os.environ.get("INPUT_JUNIT_NAME_TEMPLATE", "junit-group-{shard}.xml"),
        shard_count=int(os.environ["INPUT_SHARD_COUNT"]),
        max_files=int(os.environ.get("INPUT_MAX_FILES", str(DEFAULT_CANARY_MAX_FILES))),
        output=Path(os.environ["INPUT_OUTPUT"]),
        working_directory=Path(os.environ.get("INPUT_WORKING_DIRECTORY", ".")),
    )
    result = build_canary(config)
    _append_action_outputs(config, result)
    print(format_failure_canary_summary(result, expected_report_count=config.shard_count))
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised by the composite action entrypoint
    raise SystemExit(main())
