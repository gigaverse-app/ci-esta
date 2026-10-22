"""Consumers can safely pin a composite only when its nested actions are pinned."""

import re
from pathlib import Path


def test_shared_actions_use_immutable_nested_references() -> None:
    root = Path(__file__).resolve().parents[2]
    remote = re.compile(r"^\s*(?:-\s*)?uses:\s+(?!\./)(\S+)", re.MULTILINE)
    immutable = re.compile(r"^[^@\s]+@[0-9a-f]{40}$")
    unpinned = [
        f"{path.relative_to(root)}: {reference}"
        for path in (root / ".github/actions").glob("*/action.y*ml")
        for reference in remote.findall(path.read_text())
        if not immutable.fullmatch(reference)
    ]
    assert not unpinned, "\n".join(unpinned)
