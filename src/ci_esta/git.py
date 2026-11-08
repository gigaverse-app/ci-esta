"""The one way CI-esta reads Git."""

from __future__ import annotations

import subprocess
from pathlib import Path


def git(repo: Path, *args: str) -> str:
    """Run Git in `repo` and return its output as text; a failure raises `CalledProcessError`.

    Output is decoded as UTF-8, which is what Git writes for paths with `-z` and for blobs in
    this repository's languages, not with the locale's encoding, which differs on Windows.
    """
    # dry-lint: distinct-from actions/resolve-lane-evidence/release_version.py::git
    # That copy is a standalone script an action runs without CI-esta installed, so it cannot import this.
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="surrogateescape",
    ).stdout
