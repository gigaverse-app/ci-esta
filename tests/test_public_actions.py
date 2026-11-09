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


class _StrictLoader(yaml.SafeLoader):
    """GitHub rejects a mapping with a repeated key; PyYAML silently keeps the last one."""


def _unique_mapping(loader: yaml.SafeLoader, node: yaml.MappingNode, deep: bool = False) -> dict:
    keys = [loader.construct_object(key, deep=deep) for key, _ in node.value]
    repeated = sorted({key for key in keys if keys.count(key) > 1}, key=str)
    if repeated:
        raise yaml.constructor.ConstructorError(None, None, f"repeated keys {repeated}", node.start_mark)
    return yaml.SafeLoader.construct_mapping(loader, node, deep)


_StrictLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _unique_mapping)


@pytest.mark.parametrize("action", sorted(ROOT.glob("actions/*/action.yml")), ids=lambda path: path.parent.name)
def test_every_action_loads_the_way_github_parses_it(action: Path) -> None:
    # A repeated `value:` under one output made GitHub refuse resolve-lane-evidence entirely.
    document = yaml.load(action.read_text(encoding="utf-8"), Loader=_StrictLoader)
    if document["runs"]["using"] == "composite":
        missing = [name for name, output in (document.get("outputs") or {}).items() if "value" not in output]
        assert not missing, f"composite outputs without a value: {missing}"
