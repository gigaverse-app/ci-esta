"""Every name the supported-API page lists stays importable, so adopters' CI checks cannot break silently."""

import importlib
import importlib.util
import re
from pathlib import Path

import pytest

PAGE = Path(__file__).resolve().parents[1] / "docs/python-api.md"
ROW = re.compile(r"^\| `(ci_esta[\w.]*)` \| (.+) \|$", re.MULTILINE)
COMMANDS = re.compile(r"`(ci_esta[\w.]*)`")


def _names() -> list[tuple[str, str]]:
    """(module, name) per listed name; a row naming no attribute contributes (module, "")."""
    rows = ROW.findall(PAGE.read_text(encoding="utf-8"))
    assert rows, "the supported-API page lists no modules"
    return [(module, name) for module, cell in rows for name in (re.findall(r"`(\w+)`", cell) or [""])]


@pytest.mark.parametrize(("module", "name"), _names(), ids=lambda value: value or "module")
def test_supported_name_is_importable(module: str, name: str) -> None:
    imported = importlib.import_module(module)
    if name:
        assert hasattr(imported, name), f"{module}.{name} is listed in docs/python-api.md"


def test_module_commands_are_runnable() -> None:
    section = PAGE.read_text(encoding="utf-8").split("## Module commands", 1)[1].split("##", 1)[0]
    commands = COMMANDS.findall(section)
    assert commands
    for module in commands:
        spec = importlib.util.find_spec(module)
        assert spec is not None and (spec.submodule_search_locations is None
                                     or importlib.util.find_spec(f"{module}.__main__") is not None), module
