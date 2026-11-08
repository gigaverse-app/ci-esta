import json

import pytest
import yaml

from ci_esta.testing.workflow_adoption import check


def test_actual_workflow_mapping_covers_metadata_and_rejects_drift(tmp_path):
    workflows = {"jobs": {
        "select-tests": {}, "metadata": {},
        "test": {"needs": "select-tests", "if": "fromJSON(needs.select-tests.outputs.lanes).core2"},
        "gate": {"name": "Validation gate", "needs": ["select-tests", "metadata", "test"],
                 "steps": [{"uses": "org/repo/.github/actions/validation-gate@sha", "with": {
                     "needs": "${{ toJSON(needs) }}", "lanes": "${{ needs.select-tests.outputs.lanes || '{}' }}",
                     "lane-jobs": '{"test":["core2"]}'}}]}}}
    lane_file = tmp_path / "lanes.json"
    lane_file.write_text(json.dumps({"lanes": {"core2": {}}}))
    workflow = tmp_path / "ci.yml"
    workflow.write_text(yaml.safe_dump(workflows))
    check(workflow, lane_file)
    workflows["jobs"]["gate"]["steps"][0]["with"]["lane-jobs"] = '{"test":["core"]}'
    workflow.write_text(yaml.safe_dump(workflows))
    with pytest.raises(ValueError, match="mapping differs"):
        check(workflow, lane_file)
    workflows["jobs"]["gate"]["steps"][0]["with"]["lane-jobs"] = '{"test":["core2"]}'
    workflows["jobs"]["gate"]["needs"].remove("metadata")
    workflow.write_text(yaml.safe_dump(workflows))
    with pytest.raises(ValueError, match="outside the aggregate"):
        check(workflow, lane_file)


def gated_repository(tmp_path):
    import subprocess

    from tests.testing.git_repo import commit, write

    workflows = {
        "jobs": {
            "select-tests": {"steps": [{"uses": "gigaverse-app/ci-esta/actions/plan-work@v1"}]},
            "unit": {
                "needs": "select-tests",
                "if": "${{ fromJSON(needs.select-tests.outputs.lanes).unit }}",
                "steps": [{"run": "pytest tests/unit"}],
            },
            "gate": {
                "name": "Validation gate",
                "needs": ["select-tests", "unit"],
                "steps": [
                    {
                        "uses": "gigaverse-app/ci-esta/actions/validation-gate@v1",
                        "with": {
                            "needs": "${{ toJSON(needs) }}",
                            "lanes": "${{ needs.select-tests.outputs.lanes || '{}' }}",
                            "lane-jobs": '{"unit":["unit"]}',
                        },
                    }
                ],
            },
        }
    }
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    write(tmp_path, ".github/workflows/ci.yml", yaml.safe_dump(workflows))
    write(tmp_path, "tests/unit/test_value.py", "def test_value(): assert True\n")
    commit(tmp_path)
    return tmp_path, tmp_path / ".github/workflows/ci.yml"


def test_a_repository_without_a_lane_file_checks_against_the_inferred_lanes(tmp_path):
    repo, workflow = gated_repository(tmp_path)
    check(workflow, None, repo)


def test_an_extending_lane_file_is_checked_with_the_lanes_it_inherits(tmp_path):
    repo, workflow = gated_repository(tmp_path)
    extends = tmp_path.parent / f"{tmp_path.name}-lanes.json"
    extends.write_text(json.dumps({"extends": "workflow", "lanes": {"docs": {"inputs": ["docs/**"]}}}))
    check(workflow, extends, repo)


def test_check_workflow_reports_a_missing_gate_without_a_traceback(tmp_path, capsys):
    from ci_esta.cli import main as cli

    workflow = tmp_path / "ci.yml"
    workflow.write_text("on: push\njobs:\n  test:\n    runs-on: ubuntu-latest\n    steps: []\n", encoding="utf-8")
    lanes = tmp_path / "lanes.json"
    lanes.write_text('{"lanes": {}}', encoding="utf-8")
    assert cli(["check-workflow", "--workflow", str(workflow), "--lanes", str(lanes)]) == 2
    assert "Exactly one stable Validation gate is required" in capsys.readouterr().err

