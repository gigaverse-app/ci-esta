"""First-party actions follow compatible releases; external actions retain digests."""

import re
from pathlib import Path


def test_shared_actions_use_versioned_toolkits_and_pinned_external_actions() -> None:
    root = Path(__file__).resolve().parents[2]
    remote = re.compile(r"^\s*(?:-\s*)?uses:\s+(?!\./)(\S+)", re.MULTILINE)
    immutable = re.compile(r"^[^@\s]+@[0-9a-f]{40}$")
    toolkit = re.compile(r"^gigaverse-app/(?:ci-esta|pytest-selective)/[^@]+@v[0-9]+\.[0-9]+$")
    unpinned = [
        f"{path.relative_to(root)}: {reference}"
        for path in (root / "actions").glob("*/action.y*ml")
        for reference in remote.findall(path.read_text())
        if not (
            toolkit.fullmatch(reference)
            if reference.startswith(("gigaverse-app/ci-esta/", "gigaverse-app/pytest-selective/"))
            else immutable.fullmatch(reference)
        )
    ]
    assert not unpinned, "\n".join(unpinned)
