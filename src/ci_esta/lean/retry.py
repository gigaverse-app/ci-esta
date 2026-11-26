"""Print a targeted Lake retry command from the errors in a build log."""

import argparse
import re
import shlex
import subprocess
import sys
from collections.abc import Iterable
from pathlib import Path, PurePosixPath

from ci_esta.git import git, tracked_files

_COLOR = re.compile(r"\x1b\[[0-9;]*m")
_ERROR = re.compile(
    r"^(?:[^\t]+\t[^\t]+\t)?(?:\d{4}-\d{2}-\d{2}T\S+Z +)?"
    r"error: (.+?\.lean):\d+:\d+:"
)
_MODULE_COMPONENT = re.compile(r"[\w']+")


def targets(repo: Path, source_root: PurePosixPath, lines: Iterable[str]) -> list[str]:
    if source_root.is_absolute() or ".." in source_root.parts:
        raise ValueError("--source-root must be relative to the Git checkout")
    root = Path(git(repo, "rev-parse", "--show-toplevel").rstrip("\n"))
    tracked = set(tracked_files(root))
    modules = {}
    for line in lines:
        error = _ERROR.match(_COLOR.sub("", line))
        if not error:
            continue
        path = PurePosixPath(error[1].replace("\\", "/"))
        if path.as_posix() not in tracked or not path.is_relative_to(source_root) or not (root / path).is_file():
            continue
        parts = path.relative_to(source_root).with_suffix("").parts
        if parts and all(map(_MODULE_COMPONENT.fullmatch, parts)):
            modules[".".join(parts)] = None
    return list(modules)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ci-esta-lean retry", description=__doc__)
    parser.add_argument("log", type=Path, help="Path to a plain Lake or GitHub Actions job log, or - for stdin")
    parser.add_argument("--repo", type=Path, default=Path.cwd(), help="Any directory inside the Git checkout")
    parser.add_argument(
        "--source-root", type=PurePosixPath, default=PurePosixPath("."), help="Lake source directory (default: .)"
    )
    args = parser.parse_args(argv)
    try:
        if args.log == Path("-"):
            modules = targets(args.repo, args.source_root, sys.stdin)
        else:
            with args.log.open(encoding="utf-8", errors="replace") as lines:
                modules = targets(args.repo, args.source_root, lines)
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        print(f"ci-esta-lean retry: {error}", file=sys.stderr)
        return 1
    if modules:
        print(shlex.join(["lake", "build", *(f"+{module}" for module in modules)]))
    else:
        print("ci-esta-lean retry: no errors matched tracked Lean sources in this checkout", file=sys.stderr)
    return 0
