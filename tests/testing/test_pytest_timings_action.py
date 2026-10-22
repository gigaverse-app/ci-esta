import json
from pathlib import Path

import pytest

from ci_esta.testing.action import AggregationConfig, aggregate_artifacts, main


def _write_shard_artifacts(root: Path) -> None:
    (root / "durations-1.json").write_text(json.dumps({"tests/test_a.py::test_a": 2.0}))
    (root / "durations-2.json").write_text(json.dumps({"tests/test_b.py::test_b": 3.0}))
    (root / "junit-1.xml").write_text('<testsuite name="first" time="2.5"/>')
    (root / "junit-2.xml").write_text('<testsuite name="second" time="4.0"/>')


def test_aggregates_parameterized_shard_artifacts_and_validates_coverage(tmp_path: Path) -> None:
    _write_shard_artifacts(tmp_path)
    coverage = tmp_path / "coverage.xml"
    coverage.write_text('<coverage line-rate="0.75"/>')
    duration_output = tmp_path / "merged.json"

    result = aggregate_artifacts(
        AggregationConfig(
            artifact_directory=tmp_path,
            duration_pattern="durations-*.json",
            junit_pattern="junit-*.xml",
            shard_count=2,
            duration_output=duration_output,
            coverage_xml=coverage,
            coverage_fail_under=70.0,
        )
    )

    assert result.merged_tests == 2
    assert result.total_test_time == "6s"
    assert result.wall_time == "4s"
    assert result.coverage_percent == pytest.approx(75.0)
    assert json.loads(duration_output.read_text()) == {
        "tests/test_a.py::test_a": 2.0,
        "tests/test_b.py::test_b": 3.0,
    }


def test_rejects_incomplete_shard_artifacts(tmp_path: Path) -> None:
    _write_shard_artifacts(tmp_path)
    (tmp_path / "junit-2.xml").unlink()

    with pytest.raises(ValueError, match="expected 2 JUnit artifacts, found 1"):
        aggregate_artifacts(
            AggregationConfig(
                artifact_directory=tmp_path,
                duration_pattern="durations-*.json",
                junit_pattern="junit-*.xml",
                shard_count=2,
                duration_output=tmp_path / "merged.json",
            )
        )


def test_main_writes_action_outputs_and_step_summary(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _write_shard_artifacts(tmp_path)
    github_output = tmp_path / "github-output"
    step_summary = tmp_path / "step-summary"
    monkeypatch.setenv("INPUT_ARTIFACT_DIRECTORY", str(tmp_path))
    monkeypatch.setenv("INPUT_DURATION_PATTERN", "durations-*.json")
    monkeypatch.setenv("INPUT_JUNIT_PATTERN", "junit-*.xml")
    monkeypatch.setenv("INPUT_SHARD_COUNT", "2")
    monkeypatch.setenv("INPUT_DURATION_OUTPUT", str(tmp_path / "merged.json"))
    monkeypatch.setenv("INPUT_COVERAGE_XML", "")
    monkeypatch.setenv("INPUT_COVERAGE_FAIL_UNDER", "")
    monkeypatch.setenv("GITHUB_OUTPUT", str(github_output))
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(step_summary))

    assert main() == 0
    assert github_output.read_text().splitlines() == [
        "merged_tests=2",
        "total_test_time=6s",
        "wall_time=4s",
        "coverage_percent=",
    ]
    assert step_summary.read_text() == "Total test time: 6s  \nParallel wall time: 4s\n"
