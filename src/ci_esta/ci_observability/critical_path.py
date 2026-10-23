"""Critical-path method over an explicit, expanded workflow dependency DAG.

Observed delays are time after all declared prerequisites completed, not a claim
about runner queue causes. Execution CPM holds measured job durations constant.
"""
from __future__ import annotations

from datetime import datetime
from fnmatch import fnmatchcase
from graphlib import CycleError, TopologicalSorter
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, ConfigDict, Field

if TYPE_CHECKING:
    from ci_esta.ci_observability.models import GitHubJobV1


class PathNode(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    name: str
    needs: list[str]
    conclusion: str | None
    execution_seconds: float
    delay_seconds: float
    slack_seconds: float


class CriticalPathResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    status: Literal["complete", "unavailable"]
    reason: str = ""
    elapsed_seconds: float | None = None
    execution_seconds: float | None = None
    observed_path: list[str] = Field(default_factory=list)
    execution_path: list[str] = Field(default_factory=list)
    nodes: list[PathNode] = Field(default_factory=list)


def analyze(created_at: datetime | None, jobs: list[GitHubJobV1],
            dependencies: dict[str, list[str]], gates: list[str]) -> CriticalPathResult:
    """Reject ambiguous/incomplete evidence while leaving the ordinary report useful."""
    try:
        if created_at is None:
            raise ValueError("Run attempt start timestamp is unavailable")
        return _analyze(created_at, jobs, dependencies, gates)
    except (ValueError, CycleError) as error:
        return CriticalPathResult(status="unavailable", reason=str(error))


def _analyze(created_at, jobs, dependencies, gates):
    if not gates or not dependencies:
        raise ValueError("Explicit job dependencies and Actions gates are required")
    by_name = {job.name: job for job in jobs}
    if len(by_name) != len(jobs) or len({job.run_attempt for job in jobs}) != 1:
        raise ValueError("Duplicate job names or mixed run attempts")
    matches = {pattern: sorted(name for name in by_name if fnmatchcase(name, pattern))
               for pattern in dependencies}
    if any(not names for names in matches.values()):
        raise ValueError("A declared job pattern did not match observed jobs")
    expanded = {}
    for pattern, names in matches.items():
        for name in names:
            if name in expanded:
                raise ValueError(f"Overlapping job patterns for {name}")
            parents = dependencies[pattern]
            if any(parent not in matches for parent in parents):
                raise ValueError(f"Undeclared prerequisite for {name}")
            expanded[name] = sorted({item for parent in parents for item in matches[parent]})
    if any(gate not in expanded for gate in gates):
        raise ValueError("A required gate is missing from the declared graph")
    order = list(TopologicalSorter(expanded).static_order())
    relevant = set(gates)
    for name in reversed(order):
        if name in relevant:
            relevant.update(expanded[name])
    order = [name for name in order if name in relevant]
    durations, waits, finishes, earliest, observed_parent, execution_parent = {}, {}, {}, {}, {}, {}
    for name in order:
        item, parents = by_name[name], expanded[name]
        observed_parent[name] = max(parents, key=lambda p: (finishes[p], p), default=None)
        execution_parent[name] = max(parents, key=lambda p: (earliest[p], p), default=None)
        ready = max((finishes[p] for p in parents), default=0.0)
        if item.conclusion == "skipped":
            duration, delay, finish = 0.0, 0.0, ready
        else:
            if item.status != "completed" or item.started_at is None or item.completed_at is None:
                raise ValueError(f"Incomplete timestamps for {name}")
            start = (item.started_at - created_at).total_seconds()
            finish = (item.completed_at - created_at).total_seconds()
            if start < ready or finish < start:
                raise ValueError(f"Timestamps contradict declared dependencies for {name}")
            duration, delay = finish - start, start - ready
        durations[name], waits[name], finishes[name] = duration, delay, finish
        earliest[name] = max((earliest[p] for p in parents), default=0.0) + duration
    observed_gate = max(gates, key=lambda n: (finishes[n], n))
    execution_gate = max(gates, key=lambda n: (earliest[n], n))
    makespan = earliest[execution_gate]
    latest_finish = dict.fromkeys(order, makespan)
    for name in reversed(order):
        for parent in expanded[name]:
            latest_finish[parent] = min(latest_finish[parent], latest_finish[name] - durations[name])

    def chain(last, predecessors):
        result = []
        while last is not None:
            result.append(last)
            last = predecessors[last]
        return list(reversed(result))

    return CriticalPathResult(
        status="complete", elapsed_seconds=finishes[observed_gate], execution_seconds=makespan,
        observed_path=chain(observed_gate, observed_parent), execution_path=chain(execution_gate, execution_parent),
        nodes=[PathNode(name=name, needs=expanded[name], conclusion=by_name[name].conclusion,
                        execution_seconds=durations[name], delay_seconds=waits[name],
                        slack_seconds=max(0, latest_finish[name] - earliest[name])) for name in order],
    )
