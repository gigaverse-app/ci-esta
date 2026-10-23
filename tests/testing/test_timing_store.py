"""Public retention journeys, including independent concurrent writers."""

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import pytest

from ci_esta.testing.cli import main
from ci_esta.testing.timing_history import Observation
from ci_esta.testing.timing_store import TimingHistory, combine_histories, observation_stamp


def report(root, name, seconds):
    (root / name).write_text("def test_ok(): pass\n")
    path = root / f"{name}.xml"
    path.write_text(f'<testsuite><testcase file="{name}" time="{seconds}"/></testsuite>')
    return path


def learn(root, name, seconds, day, history="history.json"):
    path = report(root, name, seconds)
    inventory = root / f"inventory-{name}"
    inventory.write_text("test_a.py\ntest_b.py\n")
    return main([
        "learn", str(path), "--history", str(root / history), "--history-key", "unit",
        "--complete-files", "--tracked-files", str(inventory),
        "--observed-at", f"2026-10-{day:02d}T00:00:00Z", "--working-directory", str(root),
        "--output", str(root / f"costs-{name}.json"),
    ])


def test_partial_and_stale_updates_through_cli(tmp_path):
    learn(tmp_path, "test_a.py", 10, 20)
    learn(tmp_path, "test_b.py", 20, 21)
    learn(tmp_path, "test_a.py", 99, 19)
    assert json.loads((tmp_path / "costs-test_a.py.json").read_text()) == {"test_a.py": 10, "test_b.py": 20}


def test_partial_file_requires_explicit_contract(tmp_path):
    path = report(tmp_path, "test_a.py", 10)
    with pytest.raises(SystemExit):
        main(["learn", str(path), "--history", str(tmp_path / "history.json"), "--history-key", "unit"])
    assert not (tmp_path / "history.json").exists()


def test_concurrent_local_writers_preserve_both_updates(tmp_path):
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = [pool.submit(learn, tmp_path, name, seconds, day)
                   for name, seconds, day in [("test_a.py", 10, 20), ("test_b.py", 20, 21)]]
        assert [result.result() for result in results] == [0, 0]
    state = TimingHistory.model_validate_json((tmp_path / "history.json").read_text())
    assert {key: value.seconds for key, value in state.observations.items()} == {"test_a.py": 10, "test_b.py": 20}


def test_concurrent_remote_snapshots_merge_in_either_order(tmp_path):
    # Both runners started without seeing the other's state. Neither publication
    # may overwrite the other; the next reader reconciles both immutable artifacts.
    learn(tmp_path, "test_a.py", 10, 20, "runner-a.json")
    learn(tmp_path, "test_b.py", 20, 21, "runner-b.json")
    states = [TimingHistory.model_validate_json((tmp_path / file).read_text())
              for file in ["runner-a.json", "runner-b.json"]]
    now = datetime(2026, 10, 22, tzinfo=timezone.utc)
    forward = combine_histories(states, "unit", now)
    reverse = combine_histories(states[::-1], "unit", now)
    assert forward == reverse
    assert {key: value.seconds for key, value in forward.observations.items()} == {"test_a.py": 10, "test_b.py": 20}


def test_stamps_normalize_timezones():
    assert observation_stamp(datetime.fromisoformat("2026-10-20T03:00:00+03:00")) == observation_stamp(
        datetime.fromisoformat("2026-10-20T00:00:00+00:00")
    )


def test_expired_deletion_survives_late_checkpoint_and_restoration():
    removed_at = datetime(2026, 10, 1, tzinfo=timezone.utc)
    old = TimingHistory(
        key="unit", observations={"test_a.py": Observation(10, observation_stamp(removed_at))},
        tracked_files={"test_a.py"}, inventory_at=removed_at, inventory_stamp=observation_stamp(removed_at),
    )
    deletion = TimingHistory(
        key="unit", observations={}, tracked_files=set(), removed_files={"test_a.py": removed_at},
        inventory_at=removed_at, inventory_stamp=observation_stamp(removed_at, 1),
    )
    expired = combine_histories([deletion, old], "unit", removed_at.replace(day=16))
    assert expired.observations == {}
    assert expired.removed_files == {"test_a.py": removed_at}
    assert combine_histories([expired, old], "unit", removed_at.replace(day=20)).observations == {}
    restored = old.model_copy(deep=True)
    restored.inventory_at = removed_at.replace(day=21)
    restored.inventory_stamp = observation_stamp(restored.inventory_at)
    restored.observations["test_a.py"] = Observation(20, restored.inventory_stamp)
    result = combine_histories([restored, expired, old], "unit", removed_at.replace(day=22))
    assert result.observations["test_a.py"].seconds == 20
    assert result.removed_files == {}


@pytest.mark.parametrize("invalid", ["broken", '{"version":2,"key":"unit"}'])
def test_invalid_history_preserves_history_and_output(tmp_path, invalid):
    (tmp_path / "history.json").write_text(invalid)
    output = tmp_path / "costs-test_a.py.json"
    output.write_text('{"test_a.py":42}')
    with pytest.raises(SystemExit):
        learn(tmp_path, "test_a.py", 10, 20)
    assert (tmp_path / "history.json").read_text() == invalid
    assert output.read_text() == '{"test_a.py":42}'
