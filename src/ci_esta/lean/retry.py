"""Print a targeted Lake retry command from the failures in a build log."""

import argparse
import posixpath
import re
import shlex
import subprocess
import sys
import tomllib
from collections.abc import Iterable
from pathlib import Path, PurePosixPath

from ci_esta.git import git, tracked_files

_COLOR = re.compile(r"\x1b\[[0-9;]*m")
# GitHub's raw job logs start with a byte-order mark and prefix each line with a timestamp;
# `gh run view --log` prefixes the job and step names as well.
_PREFIX = r"^﻿?(?:[^\t]+\t[^\t]+\t)?(?:\d{4}-\d{2}-\d{2}T\S+Z +)?"
_ERROR = re.compile(_PREFIX + r"error: (.+?\.lean):")
# Lake names each failed job itself, including those that leave no positioned diagnostic,
# such as a bad import or a compiler killed for lack of memory.
_FAILED = re.compile(_PREFIX + r"✖ \[\d+/\d+\] \w+ (.+?)(?: \([^()]*\))?\s*$")
_SUMMARY = re.compile(_PREFIX + r"Some required targets logged failures:\s*$")
_BULLET = re.compile(_PREFIX + r"- (.+?)\s*$")
_NAME = re.compile(r"(?:«([^«»]+)»|([^.«»/:\s]+))(?:\.|$)")
_SIMPLE = re.compile(r"[^\W\d][\w'!?]*")


def _components(name: str) -> tuple[str, ...] | None:
    """Split a module name as Lake prints it, `A.«b c».D`; None for any other target."""
    parts, position = [], 0
    while position < len(name):
        component = _NAME.match(name, position)
        if not component:
            return None
        parts.append(component[1] or component[2])
        position = component.end()
    return tuple(parts) if parts and not name.endswith(".") else None


def _spell(parts: Iterable[str]) -> str | None:
    """A module name Lake accepts after `+`, quoting components that are not plain identifiers."""
    spelled = []
    for part in parts:
        if _SIMPLE.fullmatch(part):
            spelled.append(part)
        elif "«" in part or "»" in part or "\n" in part:
            return None
        else:
            spelled.append(f"«{part}»")
    return ".".join(spelled)


def _normal(path: str) -> PurePosixPath:
    return PurePosixPath(posixpath.normpath(path.replace("\\", "/")))


def project_directory(start: Path) -> Path:
    """The Lake package containing `start`, where Lake ran and its paths are relative to; else the Git root."""
    root = Path(git(start, "rev-parse", "--show-toplevel").rstrip("\n")).resolve()
    start = start.resolve()
    for directory in (start, *start.parents):
        if (directory / "lakefile.toml").is_file() or (directory / "lakefile.lean").is_file():
            return directory
        if directory == root:
            break
    return root


def source_roots(project: Path) -> list[PurePosixPath]:
    """Source directories a declarative lakefile names, deepest first; `.` when it cannot be read."""
    roots = {PurePosixPath(".")}
    try:
        config = tomllib.loads((project / "lakefile.toml").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return list(roots)
    package = config.get("srcDir", ".")
    libraries = [*config.get("lean_lib", []), *config.get("lean_exe", [])]
    if isinstance(package, str):
        roots = {_normal(package)}
        for library in libraries:
            if isinstance(library, dict) and isinstance(library.get("srcDir", "."), str):
                roots.add(_normal(posixpath.join(package, library.get("srcDir", "."))))
    roots = {root for root in roots if not root.is_absolute() and ".." not in root.parts}
    return sorted(roots or {PurePosixPath(".")}, key=lambda root: len(root.parts), reverse=True)


def targets(
    repo: Path, source_root: PurePosixPath | None, lines: Iterable[str], skipped: list[str] | None = None
) -> list[str]:
    """Failed modules in log order. `skipped` collects failures that name no tracked module here."""
    if source_root is not None and (source_root.is_absolute() or ".." in source_root.parts):
        raise ValueError("--source-root must be relative to the Lake project")
    project = project_directory(repo)
    roots = [_normal(str(source_root))] if source_root is not None else source_roots(project)
    tracked = {PurePosixPath(path) for path in tracked_files(project) if path.endswith(".lean")}
    # Lake's module names carry no source directory, so match them to a tracked file by its trailing components.
    by_suffix: dict[tuple[str, ...], PurePosixPath] = {}
    for path in sorted(tracked):
        parts = path.with_suffix("").parts
        for start in range(len(parts)):
            by_suffix.setdefault(parts[start:], path)
    modules: dict[str, None] = {}
    reported: set[PurePosixPath] = set()
    skipped = [] if skipped is None else skipped

    def lake_target(name: str) -> None:
        parts = _components(name)
        if parts is None:
            return  # A library, executable or facet such as `pkg/Lib:default`; its modules are listed separately.
        path = by_suffix.get(parts)
        if path is None or not (project / path).is_file():
            skipped.append(name)
            return
        modules[name] = None
        reported.add(path)

    in_summary = False
    for raw in lines:
        line = _COLOR.sub("", raw.rstrip("\r\n"))
        if in_summary and (bullet := _BULLET.match(line)):
            lake_target(bullet[1])
            continue
        in_summary = bool(_SUMMARY.match(line))
        if failed := _FAILED.match(line):
            lake_target(failed[1])
        elif error := _ERROR.match(line):
            path = _normal(error[1])
            if path in reported:
                continue
            if path.is_absolute() or path not in tracked or not (project / path).is_file():
                continue
            root = next((root for root in roots if path.is_relative_to(root)), None)
            name = _spell(path.relative_to(root).with_suffix("").parts) if root is not None else None
            if name:
                modules[name] = None
                reported.add(path)
            else:
                skipped.append(str(path))
    return list(modules)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ci-esta-lean retry", description=__doc__)
    parser.add_argument("log", type=Path, help="Path to a plain Lake or GitHub Actions job log, or - for stdin")
    parser.add_argument(
        "--repo", type=Path, default=Path.cwd(),
        help="The Lake project directory the log's build ran in, or any directory inside it (default: .)",
    )
    parser.add_argument(
        "--source-root", type=PurePosixPath, default=None,
        help="Lake source directory relative to the project, for logs without Lake's own failure lines "
        "(default: srcDir from lakefile.toml, else .)",
    )
    args = parser.parse_args(argv)
    skipped: list[str] = []
    try:
        if args.log == Path("-"):
            modules = targets(args.repo, args.source_root, sys.stdin, skipped)
        else:
            with args.log.open(encoding="utf-8", errors="replace") as lines:
                modules = targets(args.repo, args.source_root, lines, skipped)
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        print(f"ci-esta-lean retry: {error}", file=sys.stderr)
        return 1
    if skipped:
        names = ", ".join(dict.fromkeys(skipped))
        print(f"ci-esta-lean retry: no tracked Lean source in this project for: {names}", file=sys.stderr)
    if modules:
        print(shlex.join(["lake", "build", *(f"+{module}" for module in modules)]))
    else:
        print("ci-esta-lean retry: no errors matched tracked Lean sources in this checkout", file=sys.stderr)
    return 0
