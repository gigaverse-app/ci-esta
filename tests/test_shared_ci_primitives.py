"""Shared CI boundaries preserve missing evidence and reject malformed measurements."""
from datetime import datetime, timedelta, timezone

import pytest

from ci_esta.ci_observability.enrichment.backend.artifacts import parse_coverage_xml


@pytest.mark.parametrize("xml", ['<coverage line-rate="nan"/>', '<coverage line-rate="inf"/>',
                                 '<coverage line-rate="-0.1"/>', '<coverage line-rate="1.1"/>',
                                 '<unrelated line-rate="0.9"/>'])
def test_enrichment_does_not_present_invalid_coverage(tmp_path, xml):
    path = tmp_path / "coverage.xml"
    path.write_text(xml)
    assert parse_coverage_xml(path) is None


def test_output_writer_preserves_unicode_booleans_and_multiline_values(tmp_path, monkeypatch):
    from ci_esta.github_outputs import append_outputs
    path = tmp_path / "outputs"
    monkeypatch.setenv("GITHUB_OUTPUT", str(path))
    append_outputs(enabled=True, disabled=False, count=3, name="שלום", details="first\nsecond")
    lines = path.read_text(encoding="utf-8").splitlines()
    assert lines[:4] == ["enabled=true", "disabled=false", "count=3", "name=שלום"]
    key, delimiter = lines[4].split("<<")
    assert key == "details" and lines[5:7] == ["first", "second"] and lines[7] == delimiter


def test_elapsed_keeps_zero_but_does_not_invent_missing_or_reversed_time():
    from ci_esta.timing import elapsed_seconds
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    assert elapsed_seconds(start, start) == 0
    assert elapsed_seconds(start, start + timedelta(seconds=2)) == 2
    assert elapsed_seconds(None, start) is None
    assert elapsed_seconds(start, start - timedelta(seconds=1)) is None
    with pytest.raises(ValueError):
        elapsed_seconds(start, None, strict=True)
