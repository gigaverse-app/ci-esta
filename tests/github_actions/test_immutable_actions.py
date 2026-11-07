"""Actions use published major tags, with release tags where no major is published."""

import re
from pathlib import Path


def test_shared_actions_use_published_versions() -> None:
    root = Path(__file__).resolve().parents[2]
    remote = re.compile(r"^\s*(?:-\s*)?uses:\s+(?!\./)(\S+)", re.MULTILINE)
    major = re.compile(r"^[^@\s]+@v[1-9][0-9]*$")
    # These publishers have no moving tag for the release line in use.
    release_only = re.compile(r"^(?:astral-sh/setup-uv@v10|aquasecurity/trivy-action@v0)\.\d+\.\d+$")
    invalid = [
        f"{path.relative_to(root)}: {reference}"
        for path in (root / "actions").glob("*/action.y*ml")
        for reference in remote.findall(path.read_text())
        if not (major.fullmatch(reference) or release_only.fullmatch(reference))
    ]
    assert not invalid, "\n".join(invalid)
