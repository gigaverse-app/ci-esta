"""Every public action has one implementation under actions/NAME."""

import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
SOURCES = sorted((ROOT / "actions").glob("*/action.yml"))


@pytest.mark.parametrize("source", SOURCES, ids=lambda p: p.parent.name)
def test_named_action_is_the_implementation_without_duplicate_aliases(source):
    action = yaml.safe_load(source.read_text())
    assert not (ROOT / source.parent.name / "action.yml").exists()
    assert not list((ROOT / ".github/actions").rglob("action.y*ml"))
    assert not any(step.get("uses", "").startswith("$/") for step in action["runs"]["steps"])


def test_all_action_entry_points_use_the_canonical_namespace():
    tracked = subprocess.check_output(
        ["git", "ls-files", "*action.yml", "*action.yaml"], cwd=ROOT, text=True
    ).splitlines()
    manifests = [Path(path) for path in tracked if (ROOT / path).is_file()]
    assert manifests
    assert all(len(path.parts) == 3 and path.parts[0] == "actions" for path in manifests), manifests
