"""Plan an advisory Lean preflight from two committed Git trees."""

import argparse
import json
import posixpath
import subprocess
import sys
import tempfile
from collections import defaultdict, deque
from pathlib import Path, PurePosixPath

from selective_deps import dependency_edges, file_of, is_declaration

from ci_esta.git import git
from ci_esta.lean.retry import components, declared_roots, spell

DOCS = {
    "README.md",
    "CACHE.md",
    "GUIDE.md",
    "INDEX.md",
    "CONTENTS.md",
    "REFERENCES.md",
    "ATTRIBUTION.md",
}


class UnknownFailure(Exception):
    """A previous failure that names no Lean source at either revision, so no plan can honour it."""


def names(data):
    return {path for path in data.split("\0") if path}


def module(path, roots):
    """The module name Lake accepts after `+` for a source under one of `roots`, which are deepest first."""
    path = PurePosixPath(path)
    name = spell(path.relative_to(next(root for root in roots if path.is_relative_to(root))).with_suffix("").parts)
    if name is None:
        raise ValueError(f"{path} has no Lake module name")
    return name


def respelled(name):
    """A module name as `module` spells it, whether quoted as Lean and Lake print it or not quoted at all."""
    parts = components(name)
    return spell(parts) if parts else None


def source_roots(repo, revision, inventory):
    """Lake's source directories at `revision`: those `lakefile.toml` declares, else `src` or the package root."""
    lakefiles = blobs(repo, revision, sorted({"lakefile.toml", "lakefile.lean"} & inventory.keys()))
    if "lakefile.toml" in lakefiles:
        return declared_roots(lakefiles["lakefile.toml"].decode("utf-8", errors="replace"))
    # A `lakefile.lean` is a program this cannot evaluate. If it sets `srcDir`, or Lean sources sit
    # under `src`, keep the `src` layout this planner has always assumed; otherwise Lake's default.
    legacy = b"srcDir" in lakefiles.get("lakefile.lean", b"") or any(
        path.startswith("src/") and path.endswith(".lean") for path in inventory
    )
    return [PurePosixPath("src" if legacy else ".")]


def blobs(repo, revision, paths):
    if not paths:
        return {}
    request = b"".join(f"{revision}:{path}".encode(errors="surrogateescape") + b"\0" for path in paths)
    data = subprocess.run(
        ["git", "-C", str(repo), "cat-file", "--batch", "-Z"],
        input=request,
        stdout=subprocess.PIPE,
        check=True,
    ).stdout
    offset = 0
    found = {}
    for path in paths:
        boundary = data.index(b"\0", offset)
        header = data[offset:boundary].split()
        if len(header) != 3 or header[1] != b"blob":
            raise ValueError(f"{revision}:{path} is not a Git blob")
        start = boundary + 1
        end = start + int(header[2])
        if data[end : end + 1] != b"\0":
            raise ValueError(f"incomplete Git blob for {revision}:{path}")
        found[path] = data[start:end]
        offset = end + 1
    if offset != len(data):
        raise ValueError("unexpected trailing Git blob output")
    return found


def snapshot(repo, revision, lean, temporary):
    inventory = {}
    for row in names(git(repo, "ls-tree", "-r", "-z", revision)):
        metadata, path = row.split("\t", 1)
        inventory[path] = metadata.split()[0]
    roots = source_roots(repo, revision, inventory)
    sources = sorted(
        p for p in inventory if p.endswith(".lean") and any(PurePosixPath(p).is_relative_to(root) for root in roots)
    )
    declaration_paths = sorted(p for p in inventory if is_declaration(p))
    if any(inventory[p] not in {"100644", "100755"} for p in sources + declaration_paths):
        raise ValueError(f"{revision} contains a non-regular Lean source or dependency declaration")
    contents = blobs(repo, revision, sources + declaration_paths)
    manifests = {p: contents[p] for p in declaration_paths}
    edges = dependency_edges(manifests, inventory, revision=revision)
    files = []
    imports = {}
    modules = {module(path, roots): path for path in sources}
    if len(modules) != len(sources):
        raise ValueError("duplicate module paths")
    for index, path in enumerate(sources):
        target = temporary / f"{index}.lean"
        target.write_bytes(contents[path])
        files.append(target)
    if files:
        parsed = subprocess.run(
            [
                lean,
                "--run",
                str(Path(__file__).with_name("Imports.lean")),
                *map(str, files),
            ],
            capture_output=True,
            text=True,
            # Lean writes UTF-8 whatever the locale. Decoding a module name any other way loses its import edges.
            encoding="utf-8",
            check=False,
        )
        if parsed.returncode:
            diagnostic = (parsed.stderr or parsed.stdout).strip().splitlines()
            detail = diagnostic[0] if diagnostic else f"exit status {parsed.returncode}"
            raise ValueError(f"cannot parse Lean headers at {revision}: {detail}")
        for path, line in zip(sources, parsed.stdout.splitlines(), strict=True):
            imports[path] = {modules[m] for m in map(respelled, json.loads(line)) if m in modules}
            edges.setdefault(path, set()).update(imports[path])
    return modules, edges, imports


def plan(repo, base, head, lean, previous_failures=()):
    base, head = (
        git(repo, "rev-parse", "--verify", "--end-of-options", f"{ref}^{{commit}}").strip() for ref in (base, head)
    )
    changed = names(git(repo, "diff", "--name-only", "--no-renames", "-z", base, head, "--"))
    if not changed and not previous_failures:
        return {"mode": "none", "changed": sorted(changed), "modules": [], "retry_command": [], "command": []}
    with tempfile.TemporaryDirectory() as directory:
        old_modules, old_edges, _ = snapshot(repo, base, lean, Path(directory))
        new_modules, new_edges, new_imports = snapshot(repo, head, lean, Path(directory))

    reverse = defaultdict(set)
    for edges in (old_edges, new_edges):
        for reader, inputs in edges.items():
            for node in inputs:
                reverse[node].add(reader)
    supported = set(old_modules.values()) | set(new_modules.values()) | {file_of(p) for p in reverse} | DOCS
    # Pin, build policy and workflow changes can invalidate the entire build.
    always_full = {
        p
        for p in changed
        if p.startswith((".github/", "lakefile"))
        or p in {"lean-toolchain", "lake-manifest.json", "Challenge.lean", "comparator.json"}
    }
    fallback = sorted((changed - supported) | always_full)
    if fallback:
        return {
            "mode": "full",
            "changed": sorted(changed),
            "reason": fallback,
            "command": ["lake", "build"],
        }

    # A failure may be given as a source path or as the module name Lake and `retry` print.
    failures = {
        new_modules.get(name) or old_modules.get(name) or posixpath.normpath(failure.replace("\\", "/"))
        for failure in previous_failures
        for name in [respelled(failure)]
    }
    if unknown := sorted(failures - set(old_modules.values()) - set(new_modules.values())):
        raise UnknownFailure(f"not a Lean source at {base[:12]} or {head[:12]}: {', '.join(unknown)}")
    retry = failures & set(new_modules.values())
    predecessors = {node: None for p in sorted(changed | retry) for node in (p, f"@contents:{p}")}
    pending = deque(predecessors)
    while pending:
        parent = pending.popleft()
        for reader in sorted(reverse[parent]):
            if reader not in predecessors:
                predecessors[reader] = parent
                pending.append(reader)

    def chain(path):
        result = [path]
        while (parent := predecessors[path]) is not None:
            result.append(file_of(parent))
            path = parent
        return result[::-1]

    affected = {m: p for m, p in new_modules.items() if p in predecessors}
    affected_paths = set(affected.values())
    covered_by_importers = {dependency for path in affected_paths for dependency in new_imports.get(path, ())}
    targets = sorted(m for m, p in affected.items() if p not in covered_by_importers)
    reachable = {affected[m] for m in targets}
    pending = deque(reachable)
    while pending:
        for dependency in new_imports.get(pending.popleft(), ()):
            if dependency not in reachable:
                reachable.add(dependency)
                pending.append(dependency)
    if affected_paths - reachable:
        return {
            "mode": "full",
            "changed": sorted(changed),
            "reason": "import cycle",
            "command": ["lake", "build"],
        }
    retry_targets = sorted(m for m, p in affected.items() if p in retry)
    return {
        "mode": "targeted" if affected else "none",
        "changed": sorted(changed),
        "modules": [{"module": m, "path": p, "because": chain(p)} for m, p in sorted(affected.items())],
        "retry_command": ["lake", "build", *(f"+{m}" for m in retry_targets)] if retry_targets else [],
        "command": ["lake", "build", *(f"+{m}" for m in targets)] if affected else [],
    }


def uncommitted(repo, head):
    """Work the plan cannot see: changes not yet committed when `head` is the checked-out commit."""
    revisions = [git(repo, "rev-parse", "--verify", "--end-of-options", f"{ref}^{{commit}}") for ref in (head, "HEAD")]
    # A bare repository has no working tree, so nothing in it can be uncommitted.
    if revisions[0] != revisions[1] or git(repo, "rev-parse", "--is-inside-work-tree").strip() != "true":
        return []
    return sorted(
        names(git(repo, "diff", "--name-only", "--no-renames", "-z", "HEAD", "--"))
        | names(git(repo, "ls-files", "-z", "--others", "--exclude-standard"))
    )


def main(argv: list[str] | None = None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("base")
    parser.add_argument("head", nargs="?", default="HEAD")
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--lean", default="lean")
    parser.add_argument(
        "--previous-failure",
        action="append",
        default=[],
        metavar="PATH",
        help="build this previously failing source file or module first, even if the new diff leaves it alone",
    )
    args = parser.parse_args(argv)
    try:
        result = plan(args.repo, args.base, args.head, args.lean, args.previous_failure)
        if pending := uncommitted(args.repo, args.head):
            result["uncommitted"] = pending
            print(
                f"ci-esta-lean preflight: the plan covers committed trees only; {len(pending)} uncommitted "
                "path(s) are listed under 'uncommitted'",
                file=sys.stderr,
            )
    except UnknownFailure as error:
        parser.error(f"--previous-failure: {error}")
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        result = {"mode": "full", "reason": str(error), "command": ["lake", "build"]}
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
