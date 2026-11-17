"""Shards on a shared node must not all land on its lowest-numbered CPUs."""

import os
import random
import sys
from pathlib import Path

import pytest

from ci_esta.testing.cpu_placement import busy_fractions, place_shards, read_cpu_times
from ci_esta.testing.local_shards import LocalShardRunConfig, run_local_shards


def test_a_second_runner_on_the_node_takes_the_cpus_the_first_left_idle():
    """
    INVARIANT: with spare CPUs, no shard is placed on a CPU another process is using.

    This is the measured failure: two 16-shard runners on one 32-CPU node both pinned to CPUs 0-15.
    """
    busy = {cpu: 0.97 for cpu in range(16)} | {cpu: 0.01 for cpu in range(16, 32)}
    placed = place_shards(list(range(1, 17)), list(range(32)), busy)
    assert sorted(placed.values()) == list(range(16, 32))
    assert sorted(placed) == list(range(1, 17))


def test_every_shard_gets_a_distinct_cpu_and_the_least_busy_fill_the_gap():
    busy = {0: 0.9, 1: 0.6, 2: 0.0, 3: 0.4, 4: 0.0, 5: 0.8}
    placed = place_shards([1, 2, 3, 4], range(6), busy)
    assert len(set(placed.values())) == 4
    # Two idle CPUs, then the two least busy of the rest.
    assert sorted(placed.values()) == [1, 2, 3, 4]


def test_two_runners_that_start_together_do_not_both_choose_the_lowest_cpus():
    """Both see an idle node. Deterministic choice would collide on every CPU; random choice must not."""
    idle = {cpu: 0.0 for cpu in range(32)}
    first = place_shards(range(1, 17), range(32), idle, rng=random.Random(1))
    second = place_shards(range(1, 17), range(32), idle, rng=random.Random(2))
    assert sorted(first.values()) != list(range(16)) or sorted(second.values()) != list(range(16))
    assert len(set(first.values()) & set(second.values())) < 16


@pytest.mark.parametrize("allowed", [[0, 1, 2, 3], [4, 5]])
def test_without_spare_cpus_shards_wrap_over_the_allowed_set_in_order(allowed):
    """A runner that owns its CPUs keeps the stable mapping callers used before."""
    placed = place_shards([1, 2, 3, 4], allowed, {})
    assert [placed[shard] for shard in (1, 2, 3, 4)] == [allowed[index % len(allowed)] for index in range(4)]


def test_unmeasurable_or_empty_inputs_place_nothing_or_fall_back():
    assert place_shards([1, 2], [], {}) == {}
    assert place_shards([], [0, 1], {}) == {}
    # No measurement at all still spreads over the allowed CPUs rather than failing.
    assert len(set(place_shards([1, 2], range(8), {}).values())) == 2


def test_busy_share_comes_from_two_readings_of_the_kernel_counters(tmp_path: Path):
    stat = tmp_path / "stat"
    stat.write_text("cpu  10 0 10 80 0 0 0 0 0 0\ncpu0 100 0 0 100 0 0 0 0 0 0\ncpu1 0 0 0 200 0 0 0 0 0 0\nintr 1\n")
    before = read_cpu_times(stat)
    assert before == {0: (100, 200), 1: (0, 200)}
    stat.write_text("cpu0 190 0 0 110 0 0 0 0 0 0\ncpu1 0 0 0 300 0 0 0 0 0 0\n")
    readings = iter([before, read_cpu_times(stat)])
    fractions = busy_fractions(read=lambda: next(readings), sleep=lambda _seconds: None)
    assert fractions == {0: 0.9, 1: 0.0}
    assert busy_fractions(read=dict, sleep=lambda _seconds: None) == {}
    assert read_cpu_times(tmp_path / "missing") == {}


def test_each_shard_process_is_told_its_cpu_where_the_platform_supports_it(tmp_path: Path):
    """The runner only advises: the shard command decides whether to pin itself."""
    worker = tmp_path / "worker.py"
    worker.write_text(
        "import os, pathlib\n"
        "pathlib.Path(os.environ['OUT']).joinpath(os.environ['GV_PYTEST_SHARD_INDEX'])"
        ".write_text(os.environ.get('CI_ESTA_SHARD_CPU', ''))\n"
    )
    config = LocalShardRunConfig(shard_count=3, command=[sys.executable, str(worker)], log_dir=tmp_path / "logs",
                                 environment={"OUT": str(tmp_path)})
    assert run_local_shards(config) == 0
    told = [(tmp_path / str(shard)).read_text() for shard in (1, 2, 3)]
    if not hasattr(os, "sched_getaffinity"):
        assert told == ["", "", ""]
        return
    allowed = os.sched_getaffinity(0)
    assert all(int(cpu) in allowed for cpu in told)
    assert len(set(told)) == min(3, len(allowed))
