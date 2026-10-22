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
