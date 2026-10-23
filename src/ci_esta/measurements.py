"""Versioned execution facts shared by producers and the report collector."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class MeasurementIdentity(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)

    run_id: int = Field(ge=0)
    run_attempt: int = Field(ge=1)
    head_sha: str = Field(pattern=r"^(?:[0-9a-f]{40})?$")


class ShardInterval(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)

    index: int = Field(ge=1)
    start_seconds: float = Field(ge=0)
    end_seconds: float = Field(ge=0)
    exit_code: int

    @model_validator(mode="after")
    def ordered(self) -> ShardInterval:
        if self.end_seconds < self.start_seconds:
            raise ValueError("shard end precedes start")
        return self

    @property
    def seconds(self) -> float:
        return self.end_seconds - self.start_seconds


class ShardPoolMeasurement(MeasurementIdentity):
    schema_version: Literal["ci-esta/shards/v1"] = "ci-esta/shards/v1"
    pool: str = Field(min_length=1, max_length=200)
    configured_shards: int = Field(ge=1)
    cpu_count: int | None = Field(default=None, ge=1)
    shards: list[ShardInterval] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_indices(self) -> ShardPoolMeasurement:
        indices = [shard.index for shard in self.shards]
        if len(set(indices)) != len(indices) or max(indices) > self.configured_shards:
            raise ValueError("duplicate or out-of-range shard indices")
        return self

    @property
    def wall_seconds(self) -> float:
        return max(shard.end_seconds for shard in self.shards) - min(shard.start_seconds for shard in self.shards)

    @property
    def active_seconds(self) -> float:
        return sum(shard.seconds for shard in self.shards)

    @property
    def capacity_seconds(self) -> float:
        return len(self.shards) * self.wall_seconds


class ReusedLane(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)

    lane: str = Field(min_length=1, max_length=200)
    job: str = Field(min_length=1, max_length=500)
    source_run_id: int = Field(ge=1)
    source_attempt: int = Field(ge=1)
    source_head_sha: str = Field(pattern=r"^[0-9a-f]{40}$")
    source_job_id: int = Field(ge=1)
    source_seconds: float | None = Field(default=None, ge=0)


class ReuseMeasurement(MeasurementIdentity):
    schema_version: Literal["ci-esta/reuse/v1"] = "ci-esta/reuse/v1"
    receipt: str = Field(min_length=1, max_length=1000)
    execution_context: str = Field(default="", max_length=4000)
    lanes: list[ReusedLane] = Field(default_factory=list)


class CacheMeasurement(MeasurementIdentity):
    schema_version: Literal["ci-esta/cache/v1"] = "ci-esta/cache/v1"
    job: str = Field(min_length=1, max_length=200)
    scope: str = Field(min_length=1, max_length=1000)
    outcome: Literal["hit", "miss", "repaired", "disabled", "unavailable"]
    sync_seconds: float = Field(ge=0)


class ImageReuseMeasurement(MeasurementIdentity):
    schema_version: Literal["ci-esta/image/v1"] = "ci-esta/image/v1"
    job: str = Field(min_length=1, max_length=200)
    scope: str = Field(min_length=1, max_length=1000)
    digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")


ExecutionMeasurement = ReuseMeasurement | ShardPoolMeasurement | CacheMeasurement | ImageReuseMeasurement
