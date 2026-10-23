"""The selector owns action behavior; CI-esta preserves its public wiring."""

from pathlib import Path

import pytest
import yaml


@pytest.mark.parametrize("name", ["test-impact", "pytest-expansion"])
def test_selection_actions_delegate_every_input_and_output_to_v1(name: str) -> None:
    root = Path(__file__).resolve().parents[2]
    action = yaml.safe_load((root / f"actions/{name}/action.yml").read_text())
    steps = action["runs"]["steps"]
    assert len(steps) == 1
    assert steps[0]["uses"] == f"gigaverse-app/pytest-selective/actions/{name}@v1"
    assert steps[0]["with"] == {name: "${{ inputs." + name + " }}" for name in action["inputs"]}
    assert {name: output["value"] for name, output in action.get("outputs", {}).items()} == {
        name: "${{ steps.upstream.outputs." + name + " }}" for name in action.get("outputs", {})
    }
