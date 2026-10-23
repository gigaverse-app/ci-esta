"""Timing persistence preserves the prior output on failed publication."""

from contextlib import contextmanager
from pathlib import Path
from tempfile import NamedTemporaryFile

import pytest

from ci_esta.testing import persistence
from ci_esta.testing.junit import LearnedTimings, write_learned_timings
from ci_esta.testing.timing_store import TimingHistory, write_history


def test_failed_serialization_leaves_no_temporary_file(tmp_path):
    output = tmp_path / "timings.json"
    output.write_text('{"test_a.py": 12}')
    invalid = LearnedTimings(durations={"test_a.py": float("nan")}, unmapped_cases=0, skipped_cases=0)
    with pytest.raises(ValueError):
        write_learned_timings(invalid, output)
    assert output.read_text() == '{"test_a.py": 12}'
    assert list(tmp_path.iterdir()) == [output]


@pytest.mark.parametrize("failure", ["write", "close"])
def test_failed_file_io_preserves_old_output_and_cleans_temporary_file(tmp_path, monkeypatch, failure):
    output = tmp_path / "state.json"
    output.write_text("original")

    @contextmanager
    def failing_file(**kwargs):
        with NamedTemporaryFile(**kwargs) as temporary:
            if failure == "write":
                original_write = temporary.write

                def incomplete_write(contents):
                    original_write(contents[:2])
                    raise OSError("injected write failure")

                monkeypatch.setattr(temporary, "write", incomplete_write)
            yield temporary
        if failure == "close":
            raise OSError("injected close failure")

    monkeypatch.setattr(persistence, "NamedTemporaryFile", failing_file)
    with pytest.raises(OSError, match=f"injected {failure} failure"):
        write_history(TimingHistory(key="unit"), output)
    assert output.read_text() == "original"
    assert list(tmp_path.iterdir()) == [output]


@pytest.mark.parametrize("history", [False, True])
def test_failed_replace_preserves_old_output_and_cleans_temporary_file(tmp_path, monkeypatch, history):
    output = tmp_path / "state.json"
    output.write_text("original")

    def unavailable_replace(self, destination):
        raise OSError("filesystem replacement unavailable")

    monkeypatch.setattr(Path, "replace", unavailable_replace)
    with pytest.raises(OSError, match="replacement unavailable"):
        if history:
            write_history(TimingHistory(key="unit"), output)
        else:
            write_learned_timings(LearnedTimings(durations={}, unmapped_cases=0, skipped_cases=0), output)
    assert output.read_text() == "original"
    assert list(tmp_path.iterdir()) == [output]
