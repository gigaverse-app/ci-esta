"""Incremental timing history for complete-file scheduling observations.

Extracted from the backend timing refresh. Consumers validate measurements and
own artifact discovery, persistence and serialization. Timings are advisory;
they cannot establish test completion or eligibility.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

# A PR that has not merged main since a test file was deleted, renamed or split still runs that file.
# Its planner reads main's estimates; without the file's last observation it would price the file at
# the planner's unknown-file default (1 s) and pile other files onto its shard. Keep the estimates for
# this long after the file leaves main, counted from removal rather than from the last observation.
REMOVED_FILE_RETENTION = timedelta(days=14)


@dataclass(frozen=True)
class Observation:
    seconds: float
    stamp: str


def merge_observations(observations: dict[str, Observation], values: dict[str, float], stamp: str) -> int:
    """Update complete observed files, preserving unobserved files and newer stamps.

    ``values`` must already contain validated durations for complete test files.
    Stamps must sort lexicographically in observation order within one execution
    environment. Equal stamps are idempotent; the return value counts new nodes.
    """
    existing: dict[str, list[str]] = {}
    incoming: dict[str, dict[str, float]] = {}
    for node in observations:
        existing.setdefault(node.split("::", 1)[0], []).append(node)
    for node, seconds in values.items():
        incoming.setdefault(node.split("::", 1)[0], {})[node] = seconds
    changed = 0
    for file, measured in incoming.items():
        previous = existing.get(file, [])
        # Callers validate complete files and aggregate every shard. Replace only
        # those files so removed/renamed tests cannot retain stale weights.
        # Older reports must not resurrect nodes deleted by a newer report.
        if previous and stamp <= max(observations[node].stamp for node in previous):
            continue
        for node in previous:
            del observations[node]
        for node, seconds in measured.items():
            observations[node] = Observation(seconds, stamp)
            changed += 1
    return changed


def load_observations(
    state: dict[str, Any], tracked: set[str], now: datetime
) -> tuple[dict[str, Observation], dict[str, str]]:
    """
    Persisted estimates plus, per file no longer on main, when it was first seen missing.

    INVARIANT: a file's observations outlive its removal from main by REMOVED_FILE_RETENTION, then go.
    """
    loaded = {node: Observation(**value) for node, value in state.get("observations", {}).items()}
    removed: dict[str, str] = dict(state.get("removed_files", {}))
    for file in {node.split("::", 1)[0] for node in loaded}:
        if file in tracked:
            removed.pop(file, None)
        else:
            removed.setdefault(file, now.isoformat())
    expired = {file for file, since in removed.items() if now - datetime.fromisoformat(since) > REMOVED_FILE_RETENTION}
    observations = {node: value for node, value in loaded.items() if node.split("::", 1)[0] not in expired}
    still_known = {node.split("::", 1)[0] for node in observations}
    return observations, {file: since for file, since in removed.items() if file in still_known}
