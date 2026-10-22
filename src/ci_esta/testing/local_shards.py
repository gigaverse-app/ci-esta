"""
Run independent shard commands concurrently inside one CI runner.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class LocalShardRunConfig(BaseModel):
    """
    Validated local shard process configuration.
    """

    model_config = ConfigDict(frozen=True)

    shard_count: int = Field(ge=1)
    first_shard: int = Field(default=1, ge=1)
    last_shard: int | None = Field(default=None, ge=1)
    command: list[str] = Field(min_length=1)
    log_dir: Path
    environment: dict[str, str] = Field(default_factory=dict)
    success_tail_lines: int = Field(default=20, ge=0)
    failure_tail_lines: int = Field(default=200, ge=0)

    @model_validator(mode="after")
    def valid_range(self) -> Self:
        if not self.first_shard <= (self.last_shard or self.shard_count) <= self.shard_count:
            raise ValueError("shard range must be nonempty and inside the global shard count")
        return self

    @property
    def shard_indices(self) -> range:
        return range(self.first_shard, (self.last_shard or self.shard_count) + 1)


def _tail(path: Path, line_count: int) -> str:
    if line_count == 0:
        return ""
    return "".join(path.read_text(errors="replace").splitlines(keepends=True)[-line_count:])


def run_local_shards(config: LocalShardRunConfig) -> int:
    """
    Run every configured shard, preserve every log, and aggregate status.
    """
    config.log_dir.mkdir(parents=True, exist_ok=True)
    processes: list[tuple[int, subprocess.Popen[bytes]]] = []
    try:
        for shard_index in config.shard_indices:
            log_path = config.log_dir / f"group-{shard_index}.log"
            environment = {
                **os.environ,
                **config.environment,
                "GV_PYTEST_SHARD_INDEX": str(shard_index),
                "GV_PYTEST_SHARD_COUNT": str(config.shard_count),
            }
            with log_path.open("wb") as log:
                process = subprocess.Popen(
                    config.command,
                    env=environment,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                )
            processes.append((shard_index, process))

        failed = False
        for shard_index, process in processes:
            return_code = process.wait()
            passed = return_code == 0
            failed = failed or not passed
            status = "passed" if passed else f"failed (exit {return_code})"
            print(f"Shard {shard_index}/{config.shard_count} {status}")
            tail_lines = config.success_tail_lines if passed else config.failure_tail_lines
            tail = _tail(config.log_dir / f"group-{shard_index}.log", tail_lines)
            if tail:
                print(tail, end="" if tail.endswith("\n") else "\n")
        return int(failed)
    except BaseException:
        for _, process in processes:
            if process.poll() is None:
                process.terminate()
        for _, process in processes:
            process.wait()
        raise
