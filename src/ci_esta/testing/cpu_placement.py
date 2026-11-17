"""Give each local shard its own CPU, preferring CPUs nothing else is using.

A shard pinned to "the first N CPUs" works on a runner that owns its machine. A
Kubernetes pod without a CPU limit sees every CPU of its node, so two runner pods
on one node pin their shards to the same low-numbered CPUs and leave the rest
idle. Two identical 16-shard runs sharing a 32-CPU node took 252 s and 261 s per
shard; a third on its own node took 161 s (docs/benchmarks/2026-11-17-shard-cpus.md).
"""

from __future__ import annotations

import os
import random
import time
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

#: A CPU busier than this over the sample is treated as taken by another process.
IDLE_BELOW = 0.25
SAMPLE_SECONDS = 0.25


def read_cpu_times(stat: Path = Path("/proc/stat")) -> dict[int, tuple[int, int]]:
    """Per-CPU (busy, total) jiffies; empty where the kernel does not publish them."""
    times: dict[int, tuple[int, int]] = {}
    try:
        lines = stat.read_text().splitlines()
    except OSError:
        return times
    for line in lines:
        name, *fields = line.split()
        if not name.startswith("cpu") or not name[3:].isdigit():
            continue
        try:
            values = [int(field) for field in fields]
        except ValueError:
            continue
        if len(values) < 5:
            continue
        idle = values[3] + values[4]  # idle + iowait
        times[int(name[3:])] = (sum(values) - idle, sum(values))
    return times


def busy_fractions(
    *,
    sample_seconds: float = SAMPLE_SECONDS,
    read: Callable[[], dict[int, tuple[int, int]]] = read_cpu_times,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[int, float]:
    """Share of the sample each CPU spent busy. Empty when it cannot be measured."""
    before = read()
    if not before:
        return {}
    sleep(sample_seconds)
    after = read()
    fractions: dict[int, float] = {}
    for cpu, (busy, total) in after.items():
        if cpu not in before:
            continue
        elapsed = total - before[cpu][1]
        fractions[cpu] = (busy - before[cpu][0]) / elapsed if elapsed > 0 else 0.0
    return fractions


def read_cores(cpus: Sequence[int], root: Path = Path("/sys/devices/system/cpu")) -> dict[int, int]:
    """Physical core of each CPU, named by its lowest sibling. A CPU with no topology is its own core."""
    cores: dict[int, int] = {}
    for cpu in cpus:
        core = cpu
        try:
            text = (root / f"cpu{cpu}" / "topology" / "thread_siblings_list").read_text().strip()
            first = text.replace("-", ",").split(",")[0]
            core = int(first)
        except (OSError, ValueError):
            pass
        cores[cpu] = core
    return cores


def place_shards(
    shards: Sequence[int],
    allowed: Sequence[int],
    busy: Mapping[int, float],
    *,
    cores: Mapping[int, int] | None = None,
    idle_below: float = IDLE_BELOW,
    rng: random.Random | None = None,
) -> dict[int, int]:
    """One CPU per shard: a whole idle core each while they last, then the least busy.

    With no spare CPU the mapping wraps over the allowed set in order, which is
    what callers did before. Otherwise shards first take one hyperthread of each
    core, idle cores before busy ones, and only then second threads: two shards
    on the siblings of one core are slower than two on separate cores. Idle
    cores are taken in random order so two runners that start in the same
    instant, each seeing the whole node idle, do not both choose the same ones.
    """
    cpus = sorted(set(allowed))
    if not cpus or not shards:
        return {}
    if len(cpus) <= len(shards):
        return {shard: cpus[position % len(cpus)] for position, shard in enumerate(shards)}
    core_of = {cpu: (cores or {}).get(cpu, cpu) for cpu in cpus}
    threads: dict[int, list[int]] = {}
    for cpu in cpus:
        threads.setdefault(core_of[cpu], []).append(cpu)
    for members in threads.values():
        members.sort(key=lambda cpu: (busy.get(cpu, 0.0), cpu))
    load = {core: max(busy.get(cpu, 0.0) for cpu in members) for core, members in threads.items()}
    idle = [core for core in threads if load[core] < idle_below]
    (rng or random.SystemRandom()).shuffle(idle)
    ranked = idle + sorted((core for core in threads if load[core] >= idle_below), key=lambda core: (load[core], core))
    chosen: list[int] = []
    depth = 0
    while len(chosen) < len(shards):
        # depth 0 gives every core one shard before any core gets a second.
        chosen += [threads[core][depth] for core in ranked if len(threads[core]) > depth]
        depth += 1
    return dict(zip(shards, sorted(chosen[: len(shards)]), strict=True))


def allowed_cpus() -> list[int]:
    """CPUs this process may run on; empty where the platform has no affinity API."""
    affinity = getattr(os, "sched_getaffinity", None)
    if affinity is None:
        return []
    try:
        return sorted(affinity(0))
    except OSError:
        return []


def plan_shard_cpus(shards: Sequence[int]) -> dict[int, int]:
    """Measure the runner once and choose a CPU for every shard. Empty when unsupported."""
    cpus = allowed_cpus()
    if not cpus:
        return {}
    spare = len(cpus) > len(shards)
    return place_shards(shards, cpus, busy_fractions() if spare else {}, cores=read_cores(cpus) if spare else None)
