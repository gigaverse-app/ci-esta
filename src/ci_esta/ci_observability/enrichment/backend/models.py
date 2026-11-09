"""
Typed backend enrichment contracts.

These compatibility models are the backend-owned boundary around CI-esta's shared
`ci-observability/v1` report. They deliberately contain no generic Actions
accounting or sticky rendering.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from ci_esta.ci_observability.enrichment.models import PytestTimingMetadata
from ci_esta.ci_observability.github import GitHubCommentV1, GitHubJobsPageV1
from ci_esta.ci_observability.models import GitHubJobV1

CONTRACT_VERSION = "CI-OBS-BACKEND-ENRICH-v1"
RUNNER_TEST_SHARD_PREFIX = "Test unit behavior · runner shard"


class SlowTest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    nodeid: str
    seconds: float = Field(ge=0)


class PytestSnapshot(PytestTimingMetadata):
    """The shared shard timings, plus backend's JUnit counts and slowest tests."""

    passed: int = Field(ge=0)
    failed: int = Field(ge=0)
    errors: int = Field(ge=0)
    skipped: int = Field(ge=0)
    slowest: list[SlowTest] = Field(default_factory=list, max_length=5)


class InfraSignal(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    label: str
    line: str = Field(max_length=200)


class BackendEnrichment(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    contract_version: Literal["CI-OBS-BACKEND-ENRICH-v1"] = CONTRACT_VERSION
    pytest: PytestSnapshot | None = None
    coverage_percent: float | None = Field(default=None, ge=0, le=100)
    infra_signals: list[InfraSignal] = Field(default_factory=list)
    unavailable: list[str] = Field(default_factory=list)


class BackendExtensions(BaseModel):
    """The report's ``extensions`` object as gigaverse-backend populates it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    backend: BackendEnrichment


GitHubJob = GitHubJobV1


GitHubJobsPage = GitHubJobsPageV1


GitHubComment = GitHubCommentV1


class GitHubEnrichment(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    infra_signals: list[InfraSignal] = Field(default_factory=list)
    unavailable: list[str] = Field(default_factory=list)


class JunitTotals(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    tests: int = 0
    failures: int = 0
    errors: int = 0
    skipped: int = 0
    total_seconds: float = 0
    slowest: list[SlowTest] = Field(default_factory=list)
