"""Test data for the sticky's test-selection section, shared by the reporter, renderer and profile tests."""

from datetime import datetime, timezone

from pydantic import JsonValue
from pytest_selective.impact_models import FloorChange

from ci_esta.ci_observability.enrichment.ai import AiEnrichment, AiExtensions, WorkflowClass
from ci_esta.ci_observability.enrichment.backend.models import (
    BackendEnrichment,
    BackendExtensions,
    PytestSnapshot,
)
from ci_esta.ci_observability.github import GitHubArtifactRunV1, GitHubArtifactV1
from ci_esta.ci_observability.models import FullSuiteReferenceV1, PytestTimingMetadata

#: gigaverse-ai #2814's CI run: 4 shards, 1m 18s wall, 4m 53s of summed test time.
AI_TIMINGS = PytestTimingMetadata(shard_count=4, wall_seconds=78, total_test_seconds=293)
#: gigaverse-ai #2817, which ran the full suite: 8 shards, 3m 33s wall, 25m 44s summed.
FULL_SUITE_TIMINGS = PytestTimingMetadata(shard_count=8, wall_seconds=213, total_test_seconds=1544)
#: gigaverse-backend #5121's full-suite run and its JUnit counts.
BACKEND_SNAPSHOT = PytestSnapshot(
    shard_count=6, wall_seconds=283, total_test_seconds=1573, passed=14004, failed=0, errors=0, skipped=60
)
BACKEND_COVERAGE_PERCENT = 81.5
#: gigaverse-ai's test files at #2814, and its startup floor.
TOTAL_FILES = 1087
FLOOR_FILES = 31
FLOOR_SHARE = 0.9
REPOSITORY_ID, FORK_REPOSITORY_ID = 900, 901
RECORDED_AT = datetime(2026, 9, 30, 7, 31, tzinfo=timezone.utc)


def ai_extensions(timings: PytestTimingMetadata | None = AI_TIMINGS) -> dict[str, JsonValue]:
    enrichment = AiEnrichment(workflow_class=WorkflowClass.PYTHON_TESTS, pytest=timings)
    return AiExtensions(ai=enrichment).model_dump(mode="json")


def backend_extensions(coverage_percent: float | None = None) -> dict[str, JsonValue]:
    enrichment = BackendEnrichment(pytest=BACKEND_SNAPSHOT, coverage_percent=coverage_percent)
    return BackendExtensions(backend=enrichment).model_dump(mode="json")


def full_suite_reference(
    run_id: int,
    *,
    timings: PytestTimingMetadata = FULL_SUITE_TIMINGS,
    total_files: int = TOTAL_FILES,
    head_branch: str = "main",
    recorded_at: datetime = RECORDED_AT,
) -> FullSuiteReferenceV1:
    return FullSuiteReferenceV1(
        timings=timings, total_files=total_files, run_id=run_id, head_branch=head_branch, recorded_at=recorded_at
    )


def artifact(
    artifact_id: int,
    run_id: int,
    *,
    created_at: datetime = RECORDED_AT,
    fork: bool = False,
    expired: bool = False,
) -> GitHubArtifactV1:
    """An artifact as the REST API lists it; a fork's run has another head repository."""
    return GitHubArtifactV1(
        id=artifact_id,
        name="artifact",
        expired=expired,
        created_at=created_at,
        workflow_run=GitHubArtifactRunV1(
            id=run_id, repository_id=REPOSITORY_ID, head_repository_id=FORK_REPOSITORY_ID if fork else REPOSITORY_ID
        ),
    )


def floor(**changes: object) -> FloorChange:
    """An unchanged startup floor, overridden per test."""
    return FloorChange.model_validate({"share": FLOOR_SHARE, "before": FLOOR_FILES, "after": FLOOR_FILES, **changes})
