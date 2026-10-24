import pytest

from ci_esta.testing.test_policy import plan_workflow


@pytest.mark.parametrize(
    "event,labels,expected",
    [
        ("pull_request", [], {"cheap"}),
        ("pull_request", ["test:affected-deep"], {"cheap", "costly"}),
        ("schedule", [], {"cheap", "costly", "unchanged"}),
    ],
)
def test_workflow_helper_uses_action_defaults_and_native_selection(tmp_path, event, labels, expected):
    workflow = tmp_path / ".github/workflows/test.yml"
    workflow.parent.mkdir(parents=True)
    workflow.write_text("""jobs:
  select:
    steps:
      - id: policy
        uses: gigaverse-app/ci-esta/actions/plan-test-policy@v1
        with:
          work: '["cheap", {"id":"costly", "tags":["expensive"]}, "unchanged"]'
          affected: '${{ steps.select.outputs.lanes }}'
""")
    result = plan_workflow(
        workflow,
        "select",
        {
            "github": {
                "event_name": event,
                "sha": "abc",
                "event": {"pull_request": {"labels": [{"name": x} for x in labels]}} if event == "pull_request" else {},
            },
            "steps": {"select": {"outputs": {"lanes": '["cheap", "costly"]'}}},
        },
    )
    assert {item.work.id for item in result.runnable} == expected
