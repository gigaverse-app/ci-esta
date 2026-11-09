"""Whether planning needs Bun installed, and which file pins its version.

`plan-work` plans Bun tests from Bun's module graph; without Bun it falls back to running every lane
that holds them. A repository with Bun tests (the names the graph plans, `TEST_FILE`) and no `bun` on
PATH gets Bun installed before planning, pinned by the first version file `oven-sh/setup-bun` reads.
"""

from __future__ import annotations

import argparse
import re
import shutil
from pathlib import Path, PurePosixPath

from ci_esta.git import git
from ci_esta.testing.bun.models import TEST_FILE

#: Version files `oven-sh/setup-bun` reads, in the order a repository is likely to pin with.
VERSION_FILES = {
    ".bun-version": None,
    ".tool-versions": re.compile(r"^bun\s", re.MULTILINE),
    "package.json": re.compile(r'"packageManager"\s*:\s*"bun@'),
}


def has_bun_tests(repo: Path) -> bool:
    files = git(repo, "ls-files", "-z").split("\0")
    return any(TEST_FILE.search(PurePosixPath(path).name) for path in files if path)


def version_file(repo: Path) -> str:
    """The file that pins Bun's version, or "" for the latest Bun."""
    for name, pin in VERSION_FILES.items():
        path = repo / name
        if path.is_file() and (pin is None or pin.search(path.read_text(encoding="utf-8", errors="replace"))):
            return name
    return ""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path("."))
    parser.add_argument("--github-output", type=Path, required=True)
    args = parser.parse_args(argv)
    install = shutil.which("bun") is None and has_bun_tests(args.repo)
    with args.github_output.open("a", encoding="utf-8") as output:
        output.write(f"install={str(install).lower()}\n")
        if install:
            output.write(f"version-file={version_file(args.repo)}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
