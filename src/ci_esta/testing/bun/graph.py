"""Bun's module graph at planning time, for whole-lane selection.

Bun's bundler metafile lists every file each test bundles: its imports, followed transitively,
including text, JSON, style and asset imports. A changed file selects the lanes of the tests that
bundle it, so a README no test imports selects nothing, with no documentation rule. `bun test --changed`
still narrows the files inside a selected lane at execution time.

A test preload declared in a `bunfig*.toml` runs before every test without being imported, so a change
to it, or to anything it bundles, reaches every Bun lane. Bun's environment files (`package.json`,
lockfiles, `bunfig*.toml`, `tsconfig*.json`) reach every Bun lane until a lockfile differ maps them to
packages. A graph Bun cannot build runs every Bun lane.
"""

from __future__ import annotations

import json
import os
import posixpath
import re
import shutil
import subprocess
import tempfile
import tomllib
from pathlib import Path, PurePosixPath

from pytest_selective.impact_graph import matches, within

from ci_esta.git import git
from ci_esta.testing.lane_rules import BUN_ENVIRONMENT_FILES

TEST_FILE = re.compile(r"[._](?:test|spec)\.[cm]?[jt]sx?$")
BUNFIG = re.compile(r"(?:^|/)bunfig[^/]*\.toml$")
#: Files Bun parses for further imports; other inputs (styles, images, text) are leaves.
MODULE = re.compile(r"\.(?:[cm]?[jt]sx?|json)$")


def normalized(path: str) -> str:
    return path.replace("\\", "/").removeprefix("./")


#: How Bun resolves an extensionless relative specifier.
RESOLUTION = (
    "",
    ".ts",
    ".tsx",
    ".mts",
    ".cts",
    ".js",
    ".jsx",
    ".mjs",
    ".cjs",
    ".json",
    "/index.ts",
    "/index.tsx",
    "/index.js",
    "/index.jsx",
    "/index.mjs",
)


def repository_path(path: str, repo: Path) -> str:
    """The repository-relative form of an absolute path Bun reports.

    Bun reports real paths, so a repository under a symlinked directory (Linux /tmp, macOS /var)
    is resolved the same way.
    """
    return normalized(os.path.relpath(os.path.realpath(path), os.path.realpath(repo)))


def checked_out(path: str, files: set[str], untracked: Path | None = None) -> bool:
    """Whether `path` is a tracked file or, when `untracked` names the checkout, any file in it.

    Untracked files, such as generated code, are never changed, but their imports still count.
    """
    return path in files or (untracked is not None and not path.startswith("../") and (untracked / path).is_file())


def resolve_relative(directory: str, specifier: str, files: set[str], untracked: Path | None = None) -> str | None:
    """The file a relative specifier names from `directory`, ignoring a `?query` suffix."""
    base = posixpath.normpath(posixpath.join(directory, specifier.split("?")[0]))
    return next((base + suffix for suffix in RESOLUTION if checked_out(base + suffix, files, untracked)), None)


def build_imports(repo: Path, entries: list[str], bun: str) -> dict[str, list[dict[str, object]]]:
    """Bun's metafile import edges for `entries`: each parsed file and the imports it declares.

    `metafile.ts` reads the entries from a file, so no command-line limit caps their number. It adds
    every import that names a repository file by more than a relative path, as an edge to the absolute
    path Bun resolves: tsconfig `paths` aliases, query-suffixed imports (`./icon.svg?react`) and
    workspace packages imported by name.
    """
    with tempfile.TemporaryDirectory() as scratch:
        listed, metafile = Path(scratch) / "entries.json", Path(scratch) / "meta.json"
        listed.write_text(json.dumps(entries), encoding="utf-8")
        subprocess.run(
            [bun, "--no-install", str(Path(__file__).with_name("metafile.ts")), str(listed), str(metafile)],
            cwd=repo,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        meta = json.loads(metafile.read_text(encoding="utf-8"))
    imports = {normalized(path): list(value.get("imports", [])) for path, value in meta["inputs"].items()}
    for importer, found in meta["resolved"].items():
        # Replaces Bun's own record of the import, which names it by specifier.
        declared = imports.setdefault(repository_path(importer, repo), [])
        originals = {item["original"] for item in found}
        declared[:] = [item for item in declared if item.get("path") not in originals]
        declared.extend(found)
    return imports


def test_inputs(repo: Path, entries: list[str], bun: str, files: set[str]) -> dict[str, set[str]]:
    """Each entry file's transitive repository inputs, from Bun's import edges.

    Bun leaves an import it tree-shakes away unresolved (`external` with its relative specifier) and
    does not parse that module, so such modules are resolved here and built as further entry points
    until no new file appears. Package and built-in imports are not repository files; an import Bun
    resolved to a path the planner cannot map fails the graph rather than losing the edge.
    """
    edges: dict[str, set[str]] = {}
    pending = list(entries)
    while pending:
        imports = build_imports(repo, pending, bun)
        pending = []
        for importer, declared in imports.items():
            targets = edges.setdefault(importer, set())
            for item in declared:
                specifier = str(item.get("path", ""))
                if os.path.isabs(specifier):
                    target = repository_path(specifier, repo)
                elif not item.get("external") and checked_out(normalized(specifier), files, repo):
                    # Bun 1.4 names an import of another entry point, or of an untracked file such as
                    # generated code, by its repository path; the untracked file's own imports still count.
                    target = normalized(specifier)
                elif specifier.startswith("."):
                    # A relative specifier: an import Bun left unresolved, or (Bun 1.3) one to another entry point.
                    target = resolve_relative(posixpath.dirname(importer), specifier, files, repo)
                    if target is None:
                        raise ValueError(f"cannot resolve {specifier!r} imported by {importer}")
                elif item.get("external"):
                    continue
                else:
                    # Bun resolved it, but to no path the planner can name: never drop the edge.
                    raise ValueError(f"cannot map {specifier!r} imported by {importer}")
                targets.add(target)
                if (
                    checked_out(target, files, repo)
                    and target not in edges
                    and target not in imports
                    and MODULE.search(target)
                ):
                    pending.append(target)
        pending = sorted(set(pending))
    if missing := sorted(set(entries) - set(edges)):
        raise ValueError(f"Bun reported no inputs for {', '.join(missing)}")
    graph = {}
    for entry in entries:
        seen, queue = {entry}, [entry]
        while queue:
            for target in edges.get(queue.pop(), ()):
                if target not in seen:
                    seen.add(target)
                    queue.append(target)
        graph[entry] = seen
    return graph


def test_preloads(repo: Path, files: set[str]) -> list[str]:
    """Repository files any `bunfig*.toml` preloads before tests, top-level or under `[test]`.

    Which tests run under which configuration is a command-line choice the planner cannot see, so
    every declared preload counts for every Bun test. A package preload is covered by the lockfile.
    """
    preloads = set()
    for config in sorted(path for path in files if BUNFIG.search(path)):
        settings = tomllib.loads((repo / config).read_text(encoding="utf-8"))
        for section in (settings, settings.get("test", {})):
            declared = section.get("preload", [])
            for entry in [declared] if isinstance(declared, str) else declared:
                path = resolve_relative(posixpath.dirname(config), entry, files)
                if path is None and entry.startswith("."):
                    raise ValueError(f"{config} preloads {entry!r}, which is not a tracked file")
                if path is not None:
                    preloads.add(path)
    return sorted(preloads)


def bun_lane_reasons(
    repo: Path,
    lanes: dict[str, list[str]],
    changed: set[str],
    bun: str = "bun",
    environment: list[str] | None = BUN_ENVIRONMENT_FILES,
) -> dict[str, list[str]]:
    """Reasons each lane with Bun tests is selected; lanes without Bun tests are absent.

    `environment` is the bun-environment rule's patterns; a change to one runs every Bun lane.
    """
    files = [path for path in git(repo, "ls-files", "-z").split("\0") if path]
    deleted = changed - set(files)
    tests = sorted(path for path in files if TEST_FILE.search(PurePosixPath(path).name))
    lane_tests = {
        name: [test for test in tests if any(within(test, root) for root in roots)] for name, roots in lanes.items()
    }
    lane_deleted = {
        name: sorted(path for path in deleted if TEST_FILE.search(path) and any(within(path, root) for root in roots))
        for name, roots in lanes.items()
    }
    bun_lanes = [name for name in lanes if lane_tests[name] or lane_deleted[name]]
    if not bun_lanes:
        return {}
    reasons: dict[str, list[str]] = {
        name: [f"deleted test: {path}" for path in lane_deleted[name]] for name in bun_lanes
    }
    fired = sorted(path for path in changed if environment is not None and matches(path, environment))
    if fired:
        for name in bun_lanes:
            reasons[name].extend(f"rule bun-environment: {path}" for path in fired)
        return reasons
    executable = shutil.which(bun)
    present = sorted({test for name in bun_lanes for test in lane_tests[name]})
    try:
        if executable is None:
            raise FileNotFoundError(f"{bun} is not installed")
        preloads = test_preloads(repo, set(files))
        entries = sorted(set(present) | set(preloads))
        graph = test_inputs(repo, entries, executable, set(files)) if present else {}
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        detail = (getattr(error, "stderr", "") or str(error)).strip().splitlines()
        reason = f"full-suite fallback: Bun module graph unavailable: {detail[0] if detail else error}"
        return {name: [reason] for name in bun_lanes}
    for preload in preloads if present else ():
        if hit := sorted(graph[preload] & changed):
            for name in bun_lanes:
                reasons[name].append(f"Bun test preload: {preload} (bundles {', '.join(hit)})")
    for name in bun_lanes:
        for test in lane_tests[name]:
            if hit := sorted(graph[test] & changed):
                reasons[name].append(f"affected Bun test: {test} (bundles {', '.join(hit)})")
    return reasons
