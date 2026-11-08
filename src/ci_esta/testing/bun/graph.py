"""Bun's module graph at planning time, for whole-lane selection.

`bun build --metafile` lists every file each test bundles: its imports, followed transitively,
including text and JSON imports. A changed file selects the lanes of the tests that bundle it, so a
README no test imports selects nothing, with no documentation rule. `bun test --changed` still narrows
the files inside a selected lane at execution time.

Bun's environment files (`package.json`, lockfiles, `bunfig.toml`, `tsconfig*.json`) reach every Bun
lane until a lockfile differ maps them to packages. A graph Bun cannot build runs every Bun lane.
"""

from __future__ import annotations

import json
import os
import posixpath
import re
import shutil
import subprocess
import tempfile
from pathlib import Path, PurePosixPath

from pytest_selective.impact_graph import within

from ci_esta.git import git

TEST_FILE = re.compile(r"[._](?:test|spec)\.[cm]?[jt]sx?$")
ENVIRONMENT = re.compile(r"(?:^|/)(?:package\.json|bun\.lockb?|bunfig\.toml|tsconfig[^/]*\.json)$")


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


def build_imports(repo: Path, entries: list[str], bun: str) -> dict[str, list[dict[str, object]]]:
    """Bun's metafile import edges for `entries`: each parsed file and the imports it declares."""
    with tempfile.TemporaryDirectory() as scratch:
        metafile = Path(scratch) / "meta.json"
        subprocess.run(
            [
                bun,
                "build",
                *(f"./{entry}" for entry in entries),
                "--target=bun",
                "--packages=external",
                "--root=.",
                f"--outdir={Path(scratch) / 'dist'}",
                f"--metafile={metafile}",
            ],
            cwd=repo,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        meta = json.loads(metafile.read_text(encoding="utf-8"))
    return {normalized(path): value.get("imports", []) for path, value in meta.get("inputs", {}).items()}


def test_inputs(repo: Path, tests: list[str], bun: str, files: set[str]) -> dict[str, set[str]]:
    """Each test file's transitive repository inputs, from Bun's import edges.

    Bun leaves an import it tree-shakes away unresolved (`external` with its relative specifier) and
    does not parse that module, so such modules are resolved here and built as further entry points
    until no new file appears. Package and built-in imports are not repository files.
    """
    real_repo = os.path.realpath(repo)
    edges: dict[str, set[str]] = {}
    pending = list(tests)
    while pending:
        imports = build_imports(repo, pending, bun)
        pending = []
        for importer, declared in imports.items():
            targets = edges.setdefault(importer, set())
            for item in declared:
                specifier = str(item.get("path", ""))
                if os.path.isabs(specifier):
                    # Bun reports resolved real paths; a repository under a symlinked
                    # directory (Linux /tmp, macOS /var) must be resolved the same way.
                    targets.add(normalized(os.path.relpath(os.path.realpath(specifier), real_repo)))
                elif not item.get("external") and normalized(specifier) in files:
                    # Bun 1.4 names an import of another entry point by its repository path.
                    targets.add(normalized(specifier))
                elif specifier.startswith("."):
                    # A relative specifier: an import Bun left unresolved, or (Bun 1.3) one to another entry point.
                    base = posixpath.normpath(posixpath.join(posixpath.dirname(importer), specifier))
                    resolved = next((base + suffix for suffix in RESOLUTION if base + suffix in files), None)
                    if resolved is None:
                        raise ValueError(f"cannot resolve {specifier!r} imported by {importer}")
                    targets.add(resolved)
                    if resolved not in edges and resolved not in imports:
                        pending.append(resolved)
        pending = sorted(set(pending))
    if missing := sorted(set(tests) - set(edges)):
        raise ValueError(f"bun build reported no inputs for {', '.join(missing)}")
    graph = {}
    for test in tests:
        seen, queue = {test}, [test]
        while queue:
            for target in edges.get(queue.pop(), ()):
                if target not in seen:
                    seen.add(target)
                    queue.append(target)
        graph[test] = seen
    return graph


def bun_lane_reasons(
    repo: Path, lanes: dict[str, list[str]], changed: set[str], bun: str = "bun"
) -> dict[str, list[str]]:
    """Reasons each lane with Bun tests is selected; lanes without Bun tests are absent."""
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
    environment = sorted(path for path in changed if ENVIRONMENT.search(path))
    if environment:
        for name in bun_lanes:
            reasons[name].extend(f"Bun environment: {path}" for path in environment)
        return reasons
    executable = shutil.which(bun)
    present = sorted({test for name in bun_lanes for test in lane_tests[name]})
    try:
        if executable is None:
            raise FileNotFoundError(f"{bun} is not installed")
        graph = test_inputs(repo, present, executable, set(files)) if present else {}
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        detail = (getattr(error, "stderr", "") or str(error)).strip().splitlines()
        reason = f"full-suite fallback: Bun module graph unavailable: {detail[0] if detail else error}"
        return {name: [reason] for name in bun_lanes}
    for name in bun_lanes:
        for test in lane_tests[name]:
            if hit := sorted(graph[test] & changed):
                reasons[name].append(f"affected Bun test: {test} (bundles {', '.join(hit)})")
    return reasons
