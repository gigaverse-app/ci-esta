"""The selector owns action behavior; CI-esta preserves its public wiring."""

import re
import tomllib
from pathlib import Path

import yaml


def test_test_impact_delegates_every_input_and_output_to_the_compatible_selector() -> None:
    root = Path(__file__).resolve().parents[2]
    requirement = next(item for item in tomllib.loads((root / "pyproject.toml").read_text())["project"]["optional-dependencies"]["selection"]
                       if item.startswith("pytest-selective>="))
    version = re.match(r"pytest-selective>=([0-9]+)\.([0-9]+)\.[0-9]+", requirement)
    assert version, requirement
    revision = f"v{version[1]}.{version[2]}"
    action = yaml.safe_load((root / "actions/test-impact/action.yml").read_text())
    steps = action["runs"]["steps"]
    assert len(steps) == 1
    assert steps[0]["uses"] == f"gigaverse-app/pytest-selective/.github/actions/test-impact@{revision}"
    assert steps[0]["with"] == {name: "${{ inputs." + name + " }}" for name in action["inputs"]}
    assert {name: output["value"] for name, output in action["outputs"].items()} == {
        name: "${{ steps.upstream.outputs." + name + " }}" for name in action["outputs"]
    }
