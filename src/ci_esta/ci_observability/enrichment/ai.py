"""
Gigaverse-ai's typed enrichment profile (``CI-OBS-AI-ENRICH-v1``).

Generic Actions collection, timing, cost accounting, rendering, and
metric labels stay in the shared reporter. This profile owns only the AI
repo's pytest and Docker-build measurements that the shared reporter
cannot infer.
"""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from statistics import mean
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from ci_esta.ci_observability.enrichment.models import (
    PytestTimingMetadata,
    RepositorySignal,
)
from ci_esta.ci_observability.enrichment.primitives import (
    format_seconds,
    parse_duration_seconds,
)
from ci_esta.ci_observability.enrichment.prometheus import (
    MetricSample,
    parse_prometheus,
    sample_value,
)
from ci_esta.ci_observability.models import PYTEST_TIMING_SIGNAL

CONTRACT_VERSION = "CI-OBS-AI-ENRICH-v1"


class WorkflowClass(StrEnum):
    PYTHON_TESTS = "python_tests"
    TYPE_CHECK = "type_check"
    NON_DEFAULT_TESTS = "non_default_tests"
    DEPLOY = "deploy"


class UvStageSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    stage: str
    duration_seconds: float | None = Field(default=None, ge=0)
    cache_delta_bytes: int | None = None
    cached: bool | None = None


class BuildSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    service: str
    environment: str
    build_seconds: float | None = Field(default=None, ge=0)
    cache_hit_ratio: float | None = Field(default=None, ge=0, le=1)
    cached_steps: int | None = Field(default=None, ge=0)
    total_steps: int | None = Field(default=None, ge=0)
    image_size_bytes: int | None = Field(default=None, ge=0)
    uv_stages: list[UvStageSnapshot] = Field(default_factory=list)


class AiEnrichment(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    contract_version: Literal["CI-OBS-AI-ENRICH-v1"] = CONTRACT_VERSION
    workflow_class: WorkflowClass
    pytest: PytestTimingMetadata | None = None
    builds: list[BuildSnapshot] = Field(default_factory=list)
    unavailable: list[str] = Field(default_factory=list)


class AiExtensions(BaseModel):
    """The report's ``extensions`` object as gigaverse-ai populates it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    ai: AiEnrichment


def _optional_int(value: float | None) -> int | None:
    return int(value) if value is not None else None


def _build_snapshot(samples: list[MetricSample]) -> BuildSnapshot:
    identity = next(
        (sample for sample in samples if sample.labels.get("service") and sample.labels.get("env")),
        None,
    )
    if identity is None:
        raise ValueError("build metrics have no service/environment identity")

    stages = sorted({sample.labels["stage"] for sample in samples if sample.labels.get("stage")})
    return BuildSnapshot(
        service=identity.labels["service"],
        environment=identity.labels["env"],
        build_seconds=sample_value(samples, "docker_build_duration_seconds"),
        cache_hit_ratio=sample_value(samples, "docker_build_cache_hit_ratio"),
        cached_steps=_optional_int(sample_value(samples, "docker_build_cached_steps_total")),
        total_steps=_optional_int(sample_value(samples, "docker_build_steps_total")),
        image_size_bytes=_optional_int(sample_value(samples, "docker_build_image_size_bytes")),
        uv_stages=[
            UvStageSnapshot(
                stage=stage,
                duration_seconds=sample_value(
                    samples,
                    "uv_sync_duration_seconds",
                    stage=stage,
                ),
                cache_delta_bytes=_optional_int(
                    sample_value(
                        samples,
                        "uv_cache_delta_bytes",
                        stage=stage,
                    )
                ),
                cached=(
                    bool(sample_value(samples, "uv_cached", stage=stage))
                    if sample_value(samples, "uv_cached", stage=stage) is not None
                    else None
                ),
            )
            for stage in stages
        ],
    )


def build_deploy_extension(artifacts_dir: Path) -> AiExtensions:
    builds: list[BuildSnapshot] = []
    unavailable: list[str] = []
    for metrics_path in sorted(artifacts_dir.rglob("metrics.prom")):
        try:
            builds.append(_build_snapshot(parse_prometheus(metrics_path)))
        except (OSError, ValueError) as exc:
            unavailable.append(f"{metrics_path.parent.name}: {exc}")
    if not builds and not unavailable:
        unavailable.append("no build metric artifacts were available")
    return AiExtensions(
        ai=AiEnrichment(
            workflow_class=WorkflowClass.DEPLOY,
            builds=builds,
            unavailable=unavailable,
        )
    )


def build_workflow_extension(
    workflow_class: WorkflowClass,
    *,
    pytest_shard_count: int | None,
    pytest_wall_time: str,
    pytest_total_time: str,
) -> AiExtensions:
    pytest_snapshot = None
    unavailable: list[str] = []
    if workflow_class == WorkflowClass.PYTHON_TESTS:
        if pytest_shard_count is None:
            unavailable.append("pytest shard count was unavailable")
        else:
            pytest_snapshot = PytestTimingMetadata(
                shard_count=pytest_shard_count,
                wall_seconds=parse_duration_seconds(pytest_wall_time),
                total_test_seconds=parse_duration_seconds(pytest_total_time),
            )
    return AiExtensions(
        ai=AiEnrichment(
            workflow_class=workflow_class,
            pytest=pytest_snapshot,
            unavailable=unavailable,
        )
    )


def build_repository_signals(
    extension: AiExtensions,
) -> list[RepositorySignal]:
    ai = extension.ai
    if ai.pytest is not None:
        return [
            RepositorySignal(
                key=PYTEST_TIMING_SIGNAL,
                label="pytest",
                value=(
                    f"{ai.pytest.shard_count} shards · "
                    f"{format_seconds(ai.pytest.wall_seconds)} wall · "
                    f"{format_seconds(ai.pytest.total_test_seconds)} summed test time"
                ),
            )
        ]

    if not ai.builds:
        return []

    signals = [
        RepositorySignal(
            key="docker_builds",
            label="Docker builds",
            value=f"{len(ai.builds)} service image(s) observed",
        )
    ]
    timed_builds = [build for build in ai.builds if build.build_seconds is not None]
    if timed_builds:
        slowest = max(
            timed_builds,
            key=lambda build: build.build_seconds or 0,
        )
        signals.append(
            RepositorySignal(
                key="slowest_docker_build",
                label="Slowest Docker build",
                value=f"{slowest.service} · {format_seconds(slowest.build_seconds)}",
            )
        )
    cache_ratios = [build.cache_hit_ratio for build in ai.builds if build.cache_hit_ratio is not None]
    if cache_ratios:
        signals.append(
            RepositorySignal(
                key="mean_docker_cache_hit",
                label="Mean Docker cache hit",
                value=f"{mean(cache_ratios):.1%}",
            )
        )
    image_sizes = [build.image_size_bytes for build in ai.builds if build.image_size_bytes is not None]
    if image_sizes:
        signals.append(
            RepositorySignal(
                key="total_image_size",
                label="Total image size",
                value=f"{sum(image_sizes) / (1024 * 1024):.1f} MiB",
            )
        )
    return signals
