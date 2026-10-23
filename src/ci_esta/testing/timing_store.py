"""Validated, atomic timing history for CLI and immutable artifact consumers.

Local read/merge/write is locked. Distributed writers publish separate snapshots;
readers merge *all* available snapshots, never just the last finisher's snapshot.
"""

from __future__ import annotations

import math
import subprocess
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Literal, Self

from filelock import FileLock
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from ci_esta.testing.junit import LearnedTimings, learn_junit_timings, write_learned_timings
from ci_esta.testing.timing_history import Observation, load_observations, merge_observations


def observation_stamp(observed_at: datetime, run_id: int = 0, attempt: int = 0) -> str:
    """Use source observation time, never artifact download or merge time."""
    if observed_at.tzinfo is None or run_id < 0 or attempt < 0:
        raise ValueError("observation time must include a timezone and identifiers must be nonnegative")
    return f"{observed_at.astimezone(timezone.utc):%Y-%m-%dT%H:%M:%S.%fZ}/{run_id:020d}/{attempt:010d}"


class TimingHistory(BaseModel):
    """One environment's checkpoint. Inventory ordering is independent of download order."""

    model_config = ConfigDict(extra="forbid")
    version: Literal[1] = 1
    key: str = Field(min_length=1)
    observations: dict[str, Observation] = Field(default_factory=dict)
    inventory_stamp: str = ""
    inventory_at: AwareDatetime = datetime(1970, 1, 1, tzinfo=timezone.utc)
    tracked_files: set[str] = Field(default_factory=set)
    # Keep deletion tombstones after expiry: a delayed concurrent snapshot must
    # not resurrect a file whose retention period has already elapsed.
    removed_files: dict[str, AwareDatetime] = Field(default_factory=dict)
    covered_artifact_ids: set[int] = Field(default_factory=set)
    producer_run_id: int = 0
    producer_attempt: int = 0

    @model_validator(mode="after")
    def valid_measurements(self) -> Self:
        for name, value in self.observations.items():
            if not name or not math.isfinite(value.seconds) or value.seconds < 0 or not value.stamp:
                raise ValueError("history requires named, finite nonnegative, stamped observations")
        return self

    def expire(self, now: datetime) -> None:
        for file in {node.split("::", 1)[0] for node in self.observations}:
            if file in self.tracked_files:
                self.removed_files.pop(file, None)
            else:
                self.removed_files.setdefault(file, self.inventory_at)
        self.observations, _ = load_observations(
            {"observations": {node: asdict(value) for node, value in self.observations.items()},
             "removed_files": {file: since.isoformat() for file, since in self.removed_files.items()}},
            self.tracked_files, now,
        )

    def export(self, output: Path) -> None:
        durations: dict[str, float] = {}
        for node, value in self.observations.items():
            file = node.split("::", 1)[0]
            durations[file] = durations.get(file, 0) + value.seconds
        write_learned_timings(LearnedTimings(durations=durations, unmapped_cases=0, skipped_cases=0), output)


def combine_histories(states: list[TimingHistory], key: str, now: datetime) -> TimingHistory:
    """Reconcile independent writers using the shared complete-file merge contract."""
    if any(state.key != key for state in states):
        raise ValueError("history key mismatch; use a separate history path for each environment")
    if not states:
        return TimingHistory(key=key)
    latest = max(states, key=lambda state: state.inventory_stamp)
    result = latest.model_copy(deep=True)
    result.observations = {}
    result.covered_artifact_ids = set().union(*(state.covered_artifact_ids for state in states))
    for state in states:
        by_stamp: dict[str, dict[str, float]] = {}
        for node, value in state.observations.items():
            by_stamp.setdefault(value.stamp, {})[node] = value.seconds
        for stamp, values in sorted(by_stamp.items()):
            merge_observations(result.observations, values, stamp)
    result.expire(now)
    return result


def tracked_python_files(working_directory: Path, inventory: Path | None = None) -> set[str]:
    """Inventory the entire checkout, independently of the selected test subset."""
    if inventory is not None:
        return {line.strip() for line in inventory.read_text().splitlines() if line.strip()}
    result = subprocess.run(
        ["git", "ls-files", "-z", "--", "*.py"], cwd=working_directory, text=True, capture_output=True, check=True
    )
    return set(filter(None, result.stdout.split("\0")))


def write_history(state: TimingHistory, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as stream:
        stream.write(state.model_dump_json(indent=2) + "\n")
        temporary = Path(stream.name)
    try:
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def learn_with_history(
    reports: list[Path], *, history: Path, key: str, output: Path,
    complete_files: bool, observed_at: datetime, working_directory: Path = Path("."),
    inventory: Path | None = None, snapshots: list[TimingHistory] = (),
    run_id: int = 0, attempt: int = 0,
) -> LearnedTimings:
    """Validate before mutation; retain untouched files and reject stale observations.

``complete_files`` is the caller's declaration that it ran every case belonging
to each observed file in this lane. JUnit alone cannot prove absence of -k/-m
or node-level selection. Different fixed marker lanes require different keys.
    """
    if not complete_files:
        raise ValueError("retention requires --complete-files; partial cases within a file cannot replace its cost")
    learned = learn_junit_timings(reports, working_directory)
    tracked = tracked_python_files(working_directory, inventory)
    stamp = observation_stamp(observed_at, run_id, attempt)
    history.parent.mkdir(parents=True, exist_ok=True)
    if history.resolve() == output.resolve():
        raise ValueError("history and duration output must be different files")
    # Hold the lock across loading, merging and both atomic writes. Two local
    # producers must not independently read and then overwrite the same state.
    with FileLock(str(history) + ".lock", timeout=60):
        states = list(snapshots)
        if history.exists():
            states.append(TimingHistory.model_validate_json(history.read_bytes()))
        now = datetime.now(timezone.utc)
        state = combine_histories(states, key, now)
        if stamp > state.inventory_stamp:
            state.inventory_stamp = stamp
            state.inventory_at = observed_at
            state.tracked_files = tracked
        merge_observations(state.observations, learned.durations, stamp)
        state.producer_run_id = run_id
        state.producer_attempt = attempt
        state.expire(now)
        write_history(state, history)
        state.export(output)
    return learned
