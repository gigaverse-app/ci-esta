"""
Run independent shard commands concurrently inside one CI runner.
"""

from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

from pydantic import Field

from ci_esta.testing.runner_pools import ShardRange


class LocalShardRunConfig(ShardRange):
    """
    Validated local shard process configuration.
    """

    command: list[str] = Field(min_length=1)
    log_dir: Path
    environment: dict[str, str] = Field(default_factory=dict)
    success_tail_lines: int = Field(default=20, ge=0)
    failure_tail_lines: int = Field(default=200, ge=0)
    progress_interval_seconds: float = Field(default=60, gt=0)

def _tail(path: Path, line_count: int) -> str:
    if line_count == 0:
        return ""
    return "".join(path.read_text(errors="replace").splitlines(keepends=True)[-line_count:])


def _report(config: LocalShardRunConfig, shard_index: int, status: str, tail_lines: int) -> None:
    print(f"Shard {shard_index}/{config.shard_count} {status}", flush=True)
    tail = _tail(config.log_dir / f"group-{shard_index}.log", tail_lines)
    if tail:
        print(tail, end="" if tail.endswith("\n") else "\n", flush=True)


def _wait_for_shards(config: LocalShardRunConfig, processes: list[tuple[int, subprocess.Popen[bytes]]]) -> int:
    pending = dict(processes)
    failed = False
    next_progress = time.monotonic() + config.progress_interval_seconds
    while pending:
        for shard_index, process in list(pending.items()):
            return_code = process.poll()
            if return_code is None:
                continue
            passed = return_code == 0
            failed = failed or not passed
            status = "passed" if passed else f"failed (exit {return_code})"
            _report(config, shard_index, status, config.success_tail_lines if passed else config.failure_tail_lines)
            del pending[shard_index]
        if pending:
            if time.monotonic() >= next_progress:
                for shard_index in pending:
                    _report(config, shard_index, "still running", config.failure_tail_lines)
                next_progress = time.monotonic() + config.progress_interval_seconds
            time.sleep(min(0.1, config.progress_interval_seconds))
    return int(failed)


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

        return _wait_for_shards(config, processes)
    except BaseException:
        for _, process in processes:
            if process.poll() is None:
                process.terminate()
        for _, process in processes:
            process.wait()
        raise
