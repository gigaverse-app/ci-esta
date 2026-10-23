"""Retained scheduling hints preserve complete-file and timestamp boundaries."""

import json
from dataclasses import asdict
from datetime import datetime, timedelta, timezone

import pytest

from ci_esta.testing.timing_history import (
    REMOVED_FILE_RETENTION,
    Observation,
    load_observations,
    merge_observations,
)

REMOVED_AT = datetime(2026, 10, 8, 23, 4, tzinfo=timezone.utc)


@pytest.mark.parametrize("stamp", ["1", "2"])
def test_stale_or_equal_observations_cannot_resurrect_replaced_nodes(stamp: str) -> None:
    observations = {"a.py::new": Observation(2, "2"), "b.py::kept": Observation(7, "1")}
    assert merge_observations(observations, {"a.py::old": 99}, stamp) == 0
    assert observations == {"a.py::new": Observation(2, "2"), "b.py::kept": Observation(7, "1")}


def test_empty_update_preserves_observations() -> None:
    observations = {"a.py::test": Observation(2, "1")}
    assert merge_observations(observations, {}, "2") == 0
    assert observations == {"a.py::test": Observation(2, "1")}


def test_persisted_state_round_trip_preserves_partial_updates_and_removal_age() -> None:
    state = {
        "observations": {
            "a.py::old": {"seconds": 5, "stamp": "1"},
            "b.py::kept": {"seconds": 7, "stamp": "1"},
            "removed.py::test": {"seconds": 90, "stamp": "1"},
        },
        "processed": ["old-run:1"],
        "merged_prs": {"42": {"branch": "feature"}},
    }
    observations, removed = load_observations(state, {"a.py", "b.py"}, REMOVED_AT)
    merge_observations(observations, {"a.py::new": 2}, "3")
    state.update(observations={node: asdict(value) for node, value in observations.items()}, removed_files=removed)
    restored = json.loads(json.dumps(state))
    reloaded, removal_dates = load_observations(restored, {"a.py", "b.py"}, REMOVED_AT + timedelta(days=1))
    assert merge_observations(reloaded, {"a.py::old": 99}, "2") == 0
    assert reloaded == {
        "a.py::new": Observation(2, "3"),
        "b.py::kept": Observation(7, "1"),
        "removed.py::test": Observation(90, "1"),
    }
    assert removal_dates == {"removed.py": REMOVED_AT.isoformat()}
    assert restored["processed"] == ["old-run:1"]
    assert restored["merged_prs"] == {"42": {"branch": "feature"}}


def test_partial_runs_preserve_unobserved_tests_and_newest_values() -> None:
    observations = {"a.py::old": Observation(3, "2"), "b.py::untouched": Observation(8, "1")}
    assert merge_observations(observations, {"a.py::old": 1, "a.py::new": 2}, "3") == 2
    assert merge_observations(observations, {"a.py::old": 99}, "1") == 0
    assert observations == {
        "a.py::old": Observation(1, "3"),
        "a.py::new": Observation(2, "3"),
        "b.py::untouched": Observation(8, "1"),
    }


def test_new_complete_file_measurement_retires_removed_nodes() -> None:
    observations = {"a.py::removed": Observation(100, "1"), "b.py::kept": Observation(7, "1")}
    merge_observations(observations, {"a.py::replacement": 2}, "3")
    merge_observations(observations, {"a.py::removed": 100}, "2")
    assert observations == {"a.py::replacement": Observation(2, "3"), "b.py::kept": Observation(7, "1")}


def test_a_file_removed_from_main_keeps_its_estimates_for_the_retention_window() -> None:
    state = {
        "observations": {"old.py::slow": {"seconds": 90, "stamp": "1"}, "kept.py::t": {"seconds": 2, "stamp": "1"}}
    }
    observations, removed = load_observations(state, {"kept.py"}, REMOVED_AT)
    assert observations == {"old.py::slow": Observation(90, "1"), "kept.py::t": Observation(2, "1")}
    assert removed == {"old.py": REMOVED_AT.isoformat()}

    # The window counts from removal, not from the file's last observation, and later loads keep that start.
    later = {"observations": state["observations"], "removed_files": removed}
    observations, removed = load_observations(later, {"kept.py"}, REMOVED_AT + REMOVED_FILE_RETENTION)
    assert "old.py::slow" in observations and removed == {"old.py": REMOVED_AT.isoformat()}

    expired, removed = load_observations(later, {"kept.py"}, REMOVED_AT + REMOVED_FILE_RETENTION + timedelta(seconds=1))
    assert expired == {"kept.py::t": Observation(2, "1")} and removed == {}


def test_a_file_restored_to_main_is_no_longer_counted_as_removed() -> None:
    state = {
        "observations": {"back.py::t": {"seconds": 5, "stamp": "1"}},
        "removed_files": {"back.py": "2026-01-01T00:00:00+00:00"},
    }
    observations, removed = load_observations(state, {"back.py"}, REMOVED_AT)
    assert observations == {"back.py::t": Observation(5, "1")} and removed == {}
