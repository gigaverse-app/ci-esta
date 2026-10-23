from pathlib import Path

import pytest

from ci_esta.testing.canary_action import CanaryConfig, build_canary, main


def _write_reports(root: Path) -> None:
    tests_dir = root / "tests"
    tests_dir.mkdir(exist_ok=True)
    (tests_dir / "test_a.py").touch()
    (tests_dir / "test_b.py").touch()
    (root / "junit-group-1.xml").write_text(
        '<testsuite><testcase file="tests/test_a.py" name="test_a"><failure /></testcase></testsuite>'
    )
    (root / "junit-group-2.xml").write_text(
        '<testsuite><testcase file="tests/test_b.py" name="test_b"><error /></testcase></testsuite>'
    )


def test_builds_bounded_whole_file_canary_from_complete_shard_artifacts(tmp_path: Path) -> None:
    _write_reports(tmp_path)
    output = tmp_path / "canary.txt"

    result = build_canary(
        CanaryConfig(
            artifact_directory=tmp_path,
            junit_pattern="junit-*.xml",
            shard_count=2,
            max_files=1,
            working_directory=tmp_path,
            output=output,
        )
    )

    assert output.read_text() == "tests/test_a.py\n"
    assert result.selected_file_count == 1
    assert result.failing_file_count == 2
    assert result.terminal_failure_count == 2
    assert result.has_files is True
    assert result.truncated is True
    assert result.report_count == 2
    assert result.artifacts_complete is True


def test_uses_available_reports_without_turning_incomplete_artifacts_into_a_new_failure(tmp_path: Path) -> None:
    _write_reports(tmp_path)
    (tmp_path / "junit-group-2.xml").unlink()

    result = build_canary(
        CanaryConfig(
            artifact_directory=tmp_path,
            junit_pattern="junit-*.xml",
            shard_count=2,
            working_directory=tmp_path,
            output=tmp_path / "canary.txt",
        )
    )

    assert result.selected_file_count == 1
    assert result.report_count == 1
    assert result.artifacts_complete is False


def test_empty_prior_artifacts_fall_through_to_the_full_suite(tmp_path: Path) -> None:
    output = tmp_path / "canary.txt"

    result = build_canary(
        CanaryConfig(
            artifact_directory=tmp_path,
            junit_pattern="junit-*.xml",
            shard_count=2,
            working_directory=tmp_path,
            output=output,
        )
    )

    assert output.read_text() == ""
    assert result.has_files is False
    assert result.report_count == 0
    assert result.artifacts_complete is False


def test_corrupt_report_is_not_counted_as_complete_evidence(tmp_path: Path) -> None:
    _write_reports(tmp_path)
    (tmp_path / "junit-group-2.xml").write_text("<testsuite>")

    result = build_canary(
        CanaryConfig(
            artifact_directory=tmp_path,
            junit_pattern="junit-*.xml",
            shard_count=2,
            working_directory=tmp_path,
            output=tmp_path / "canary.txt",
        )
    )

    assert result.report_count == 2
    assert result.valid_report_count == 1
    assert result.invalid_report_count == 1
    assert result.artifacts_complete is False


def test_duplicate_shard_reports_are_not_counted_as_complete_evidence(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    (first / "junit-1.xml").write_text('<testsuite name="pytest"/>')
    (second / "junit-1.xml").write_text('<testsuite name="pytest"/>')

    result = build_canary(
        CanaryConfig(
            artifact_directory=tmp_path,
            junit_pattern="**/junit-*.xml",
            junit_name_template="junit-{shard}.xml",
            shard_count=2,
            working_directory=tmp_path,
            output=tmp_path / "canary.txt",
        )
    )

    assert result.distinct_shard_count == 1
    assert result.artifacts_complete is False


@pytest.mark.parametrize(("field", "value"), [("shard_count", 0), ("max_files", 0)])
def test_rejects_nonpositive_bounds(tmp_path: Path, field: str, value: int) -> None:
    values = {
        "artifact_directory": tmp_path,
        "junit_pattern": "junit-*.xml",
        "shard_count": 2,
        "max_files": 5,
        "output": tmp_path / "canary.txt",
    }
    values[field] = value

    with pytest.raises(ValueError, match=f"{field} must be at least 1"):
        CanaryConfig.model_validate(values)


@pytest.mark.parametrize("template", ["junit.xml", "junit-{shard}-{shard}.xml", "dir/junit-{shard}.xml"])
def test_rejects_ambiguous_shard_name_templates(tmp_path: Path, template: str) -> None:
    with pytest.raises(ValueError, match="exactly one"):
        CanaryConfig(
            artifact_directory=tmp_path,
            junit_pattern="junit-*.xml",
            junit_name_template=template,
            shard_count=2,
            output=tmp_path / "canary.txt",
        )


def test_main_writes_stable_action_outputs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _write_reports(tmp_path)
    github_output = tmp_path / "github-output"
    monkeypatch.setenv("INPUT_ARTIFACT_DIRECTORY", str(tmp_path))
    monkeypatch.setenv("INPUT_JUNIT_PATTERN", "junit-*.xml")
    monkeypatch.setenv("INPUT_SHARD_COUNT", "2")
    monkeypatch.setenv("INPUT_MAX_FILES", "5")
    monkeypatch.setenv("INPUT_OUTPUT", str(tmp_path / "canary.txt"))
    monkeypatch.setenv("INPUT_WORKING_DIRECTORY", str(tmp_path))
    monkeypatch.setenv("GITHUB_OUTPUT", str(github_output))

    assert main() == 0
    outputs = dict(line.split("=", 1) for line in github_output.read_text().splitlines())
    assert outputs == {
        "canary_file": str(tmp_path / "canary.txt"),
        "selected_file_count": "2",
        "failing_file_count": "2",
        "terminal_failure_count": "2",
        "has_files": "true",
        "truncated": "false",
        "report_count": "2",
        "valid_report_count": "2",
        "invalid_report_count": "0",
        "distinct_shard_count": "2",
        "stale_file_count": "0",
        "invalid_path_count": "0",
        "artifacts_complete": "true",
    }


def test_main_does_not_require_github_output_outside_actions(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _write_reports(tmp_path)
    monkeypatch.setenv("INPUT_ARTIFACT_DIRECTORY", str(tmp_path))
    monkeypatch.setenv("INPUT_JUNIT_PATTERN", "junit-*.xml")
    monkeypatch.setenv("INPUT_SHARD_COUNT", "2")
    monkeypatch.setenv("INPUT_OUTPUT", str(tmp_path / "canary.txt"))
    monkeypatch.setenv("INPUT_WORKING_DIRECTORY", str(tmp_path))
    monkeypatch.delenv("INPUT_MAX_FILES", raising=False)
    monkeypatch.delenv("GITHUB_OUTPUT", raising=False)

    assert main() == 0


def test_composite_action_exposes_planner_inputs_and_outputs() -> None:
    action = Path("actions/pytest-failure-canary/action.yml").read_text()

    for action_input in (
        "artifact-directory",
        "junit-pattern",
        "junit-name-template",
        "shard-count",
        "max-files",
        "working-directory",
        "output",
    ):
        assert f"  {action_input}:" in action
    for action_output in (
        "canary-file",
        "selected-file-count",
        "failing-file-count",
        "terminal-failure-count",
        "has-files",
        "truncated",
        "report-count",
        "valid-report-count",
        "invalid-report-count",
        "distinct-shard-count",
        "stale-file-count",
        "invalid-path-count",
        "artifacts-complete",
    ):
        assert f"  {action_output}:" in action
    assert "python -m ci_esta.testing.canary_action" in action
