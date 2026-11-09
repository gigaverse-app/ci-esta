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


def test_existing_required_aggregate_keeps_its_name(tmp_path):
    workflows = {"jobs": {
        "select-tests": {}, "test": {"needs": "select-tests", "if": "fromJSON(needs.select-tests.outputs.lanes).core"},
        "required": {"name": "All required checks", "needs": ["select-tests", "test"],
                     "steps": [{"uses": "gigaverse-app/ci-esta/actions/validation-gate@v1", "with": {
                         "needs": "${{ toJSON(needs) }}", "lanes": "${{ needs.select-tests.outputs.lanes || '{}' }}",
                         "lane-jobs": '{"test":["core"]}'}}]}}}
    lane_file = tmp_path / "lanes.json"
    lane_file.write_text(json.dumps({"lanes": {"core": {}}}))
    workflow = tmp_path / "ci.yml"
    workflow.write_text(yaml.safe_dump(workflows))
    check(workflow, lane_file, gate_name="All required checks")
    with pytest.raises(ValueError, match="'Validation gate'"):
        check(workflow, lane_file)


def test_check_workflow_reports_a_missing_gate_without_a_traceback(tmp_path, capsys):
    from ci_esta.cli import main as cli

    workflow = tmp_path / "ci.yml"
    workflow.write_text("on: push\njobs:\n  test:\n    runs-on: ubuntu-latest\n    steps: []\n", encoding="utf-8")
    lanes = tmp_path / "lanes.json"
    lanes.write_text('{"lanes": {}}', encoding="utf-8")
    assert cli(["check-workflow", "--workflow", str(workflow), "--lanes", str(lanes)]) == 2
    assert "Exactly one aggregate job named 'Validation gate'" in capsys.readouterr().err


def reuse_workflow(matrix_os: list[str], lane_keys: dict, lanes_input: str = "${{ env.TEST_LANE_JOBS }}") -> dict:
    test_jobs = {
        f"py311-{os}": f"Test (Python 3.11, {os})" for os in ("ubuntu-latest", "windows-latest")
    } | {"minimum": "pytest-minimum"}
    gate_jobs = '{"test":["tests"],"pytest-minimum":["tests"]}'
    return {
        "env": {"TEST_LANE_JOBS": json.dumps(test_jobs)},
        "jobs": {
            "select-tests": {"steps": [
                {"id": "plan", "uses": "gigaverse-app/pytest-selective/actions/plan-lanes@v1"},
                {"id": "evidence", "uses": "gigaverse-app/ci-esta/actions/resolve-lane-evidence@v1", "with": {
                    "lanes": lanes_input, "planned-lanes": "${{ steps.plan.outputs.lanes }}",
                    "lane-keys": json.dumps(lane_keys)}},
            ]},
            "test": {
                "name": "Test (Python ${{ matrix.python }}, ${{ matrix.os }})",
                "needs": "select-tests", "if": "fromJSON(needs.select-tests.outputs.lanes).tests",
                "strategy": {"matrix": {"python": ["3.11"], "os": matrix_os}},
            },
            "pytest-minimum": {"needs": "select-tests", "if": "fromJSON(needs.select-tests.outputs.lanes).tests"},
            "gate": {"name": "Validation gate", "needs": ["select-tests", "test", "pytest-minimum"],
                     "steps": [{"uses": "gigaverse-app/ci-esta/actions/validation-gate@v1", "with": {
                         "needs": "${{ toJSON(needs) }}", "lanes": "${{ needs.select-tests.outputs.lanes || '{}' }}",
                         "lane-jobs": gate_jobs}}]},
        },
    }


ALL_KEYS = {"tests": ["py311-ubuntu-latest", "py311-windows-latest", "minimum"]}


def check_reuse(tmp_path, workflow: dict) -> None:
    lane_file = tmp_path / "lanes.json"
    lane_file.write_text(json.dumps({"lanes": {"tests": {}}}))
    path = tmp_path / "ci.yml"
    path.write_text(yaml.safe_dump(workflow, sort_keys=False))
    check(path, lane_file)


def test_lane_keys_naming_every_gated_job_and_matrix_cell_pass(tmp_path):
    check_reuse(tmp_path, reuse_workflow(["ubuntu-latest", "windows-latest"], ALL_KEYS))


def test_a_matrix_cell_missing_from_lane_keys_is_rejected(tmp_path):
    # Adding macOS without listing it would let a failing macOS cell be skipped as proven.
    with pytest.raises(ValueError, match=r"omit jobs it gates: \['Test \(Python 3.11, macos-latest\)'\]"):
        check_reuse(tmp_path, reuse_workflow(["ubuntu-latest", "windows-latest", "macos-latest"], ALL_KEYS))


def test_a_gated_job_missing_from_lane_keys_is_rejected(tmp_path):
    keys = {"tests": ["py311-ubuntu-latest", "py311-windows-latest"]}
    with pytest.raises(ValueError, match=r"omit jobs it gates: \['pytest-minimum'\]"):
        check_reuse(tmp_path, reuse_workflow(["ubuntu-latest", "windows-latest"], keys))


def test_unknown_keys_and_unreadable_maps_are_rejected(tmp_path):
    with pytest.raises(ValueError, match="must list keys of lanes"):
        check_reuse(tmp_path, reuse_workflow(["ubuntu-latest", "windows-latest"], {"tests": ["nope"]}))
    with pytest.raises(ValueError, match="literal JSON"):
        check_reuse(tmp_path, reuse_workflow(["ubuntu-latest"], ALL_KEYS, lanes_input="${{ steps.x.outputs.lanes }}"))


def test_a_dynamic_matrix_cannot_be_verified_and_is_rejected(tmp_path):
    workflow = reuse_workflow(["ubuntu-latest", "windows-latest"], ALL_KEYS)
    workflow["jobs"]["test"]["strategy"]["matrix"] = "${{ fromJSON(needs.select-tests.outputs.matrix) }}"
    with pytest.raises(ValueError, match="static matrix"):
        check_reuse(tmp_path, workflow)


def test_default_job_names_follow_githubs_matrix_naming(tmp_path):
    workflow = reuse_workflow(["ubuntu-latest", "windows-latest"], ALL_KEYS)
    del workflow["jobs"]["test"]["name"]
    jobs = json.loads(workflow["env"]["TEST_LANE_JOBS"])
    jobs.update({"py311-ubuntu-latest": "test (3.11, ubuntu-latest)", "py311-windows-latest": "test (3.11, windows-latest)"})
    workflow["env"]["TEST_LANE_JOBS"] = json.dumps(jobs)
    check_reuse(tmp_path, workflow)


def plain_gate_workflow(gate_needs: list[str]) -> dict:
    """A Validation gate with no planner and no lanes, as agent setup adds to a workflow with none."""
    return {"on": "pull_request", "jobs": {
        "tests": {"runs-on": "ubuntu-latest", "strategy": {"matrix": {"python": ["3.12", "3.13"]}},
                  "steps": [{"run": "tox -e py${{ matrix.python }}"}]},
        "typing": {"runs-on": "ubuntu-latest", "steps": [{"run": "tox -e typing"}]},
        "gate": {"name": "Validation gate", "needs": gate_needs, "if": "${{ !cancelled() }}",
                 "runs-on": "ubuntu-latest",
                 "steps": [{"uses": "gigaverse-app/ci-esta/actions/validation-gate@v1",
                            "with": {"needs": "${{ toJSON(needs) }}"}}]}}}


def test_a_plain_gate_without_lanes_passes_when_every_job_reaches_it(tmp_path, capsys):
    from ci_esta.cli import main as cli

    workflow = tmp_path / "ci.yml"
    workflow.write_text(yaml.safe_dump(plain_gate_workflow(["tests", "typing"])), encoding="utf-8")
    assert cli(["check-workflow", "--workflow", str(workflow), "--repo", str(tmp_path)]) == 0
    assert "every job reaches the gate (no lanes)" in capsys.readouterr().out


def test_a_plain_gate_still_rejects_a_job_outside_it(tmp_path):
    workflow = tmp_path / "ci.yml"
    workflow.write_text(yaml.safe_dump(plain_gate_workflow(["tests"])), encoding="utf-8")
    with pytest.raises(ValueError, match=r"outside the aggregate gate: \['typing'\]"):
        check(workflow, None, tmp_path)


def test_a_plain_gate_must_pass_every_need_to_the_action(tmp_path):
    document = plain_gate_workflow(["tests", "typing"])
    document["jobs"]["gate"]["steps"][0]["with"] = {"needs": "${{ toJSON(needs.tests) }}"}
    workflow = tmp_path / "ci.yml"
    workflow.write_text(yaml.safe_dump(document), encoding="utf-8")
    with pytest.raises(ValueError, match="must validate all direct needs"):
        check(workflow, None, tmp_path)


def test_a_lane_condition_without_a_gate_mapping_is_not_a_plain_gate(tmp_path):
    repo, workflow = gated_repository(tmp_path)
    document = yaml.safe_load(workflow.read_text())
    document["jobs"]["gate"]["steps"][0]["with"].pop("lane-jobs")
    workflow.write_text(yaml.safe_dump(document))
    with pytest.raises(ValueError, match="mapping differs"):
        check(workflow, None, repo)
