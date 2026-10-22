"""The public runner plan covers every global shard once, including uneven tails."""

import json
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.parametrize("shards,capacity", [(1, 12), (12, 12), (13, 12), (55, 2), (64, 2)])
def test_pool_cli_assigns_global_ranges_once(tmp_path: Path, shards: int, capacity: int) -> None:
    output = tmp_path / "outputs"
    result = subprocess.run(
        [sys.executable, "-m", "ci_esta.testing.cli", "pools", "--shards", str(shards),
         "--shards-per-runner", str(capacity), "--github-output", str(output)],
        capture_output=True, text=True, check=True,
    )
    pools = json.loads(result.stdout)
    assigned = [n for pool in pools for n in range(pool["first_shard"], pool["last_shard"] + 1)]
    assert assigned == list(range(1, shards + 1))
    assert all(pool["last_shard"] - pool["first_shard"] < capacity for pool in pools)
    assert all(pool["shard_count"] == shards for pool in pools)
    assert [pool["id"] for pool in pools] == [str(n) for n in range(1, len(pools) + 1)]
    outputs = dict(line.split("=", 1) for line in output.read_text().splitlines())
    assert json.loads(outputs["pools"]) == pools
    assert int(outputs["count"]) == len(pools)


@pytest.mark.parametrize("shards,capacity", [(0, 2), (4, 0), (-1, 2)])
def test_invalid_pool_request_emits_no_reusable_plan(tmp_path: Path, shards: int, capacity: int) -> None:
    output = tmp_path / "outputs"
    result = subprocess.run(
        [sys.executable, "-m", "ci_esta.testing.cli", "pools", "--shards", str(shards),
         "--shards-per-runner", str(capacity), "--github-output", str(output)],
        capture_output=True, text=True,
    )
    assert result.returncode != 0
    assert not output.exists()
