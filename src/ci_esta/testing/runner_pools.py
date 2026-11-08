"""Partition a global shard plan into bounded runner assignments."""

from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ShardRange(BaseModel):
    """Global identities remain stable whether a runner owns all shards or a range."""

    model_config = ConfigDict(frozen=True)
    shard_count: int = Field(ge=1)
    first_shard: int = Field(default=1, ge=1)
    last_shard: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def valid_range(self) -> Self:
        if not self.first_shard <= (self.last_shard or self.shard_count) <= self.shard_count:
            raise ValueError("shard range must be nonempty and inside the global shard count")
        return self

    @property
    def shard_indices(self) -> range:
        return range(self.first_shard, (self.last_shard or self.shard_count) + 1)


class RunnerPool(ShardRange):
    """An executable GitHub matrix assignment with a stable string pool ID."""

    id: str


def plan_runner_pools(shard_count: int, shards_per_runner: int) -> list[RunnerPool]:
    if shards_per_runner < 1:
        raise ValueError("shards_per_runner must be positive")
    ShardRange(shard_count=shard_count)
    # Consecutive, disjoint ranges retain the global count and cover the uneven
    # final pool too. Consumers execute these assignments rather than recomputing.
    return [
        RunnerPool(id=str(index), shard_count=shard_count, first_shard=first,
                   last_shard=min(first + shards_per_runner - 1, shard_count))
        for index, first in enumerate(range(1, shard_count + 1, shards_per_runner), start=1)
    ]
