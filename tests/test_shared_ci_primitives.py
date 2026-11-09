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


@pytest.mark.parametrize("seconds, expected", [(0, "0 runner-s"), (59, "59 runner-s"), (90, "2 runner-min")])
def test_runner_units_preserve_rounded_cost_presentation(seconds, expected):
    from ci_esta.timing import format_duration
    assert format_duration(seconds, style="runner") == expected


def test_drill_reads_jobs_after_the_first_api_page(monkeypatch):
    from urllib.parse import parse_qs, urlparse

    from ci_esta import drill

    pages = []
    def api(path):
        number = int(parse_qs(urlparse(path).query)["page"][0])
        pages.append(number)
        return {"jobs": [{"id": index} for index in (range(100) if number == 1 else [100])]}
    monkeypatch.setattr(drill, "_api", api)
    profile = drill.ConsumerProfile(repository="example/repo", workflow="ci.yml", plan_job="plan", pytest_job="tests",
                                    touch_path="src/feature.py", broad_path="pyproject.toml", always_runs=())
    assert [job["id"] for job in drill._jobs(profile, {"id": 1})] == list(range(101))
    assert pages == [1, 2]
