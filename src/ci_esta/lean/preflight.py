"""Plan an advisory Lean preflight from two committed Git trees."""

import argparse
import json
import subprocess
import tempfile
from collections import defaultdict, deque
from pathlib import Path, PurePosixPath

from selective_deps import dependency_edges, file_of, is_declaration

DOCS = {
    "README.md",
    "CACHE.md",
    "GUIDE.md",
    "INDEX.md",
    "CONTENTS.md",
    "REFERENCES.md",
    "ATTRIBUTION.md",
}


def git(repo, *args):
    return subprocess.check_output(["git", "-C", str(repo), *args])


def names(data):
    return {s.decode() for s in data.split(b"\0") if s}


def module(path):
    return ".".join(PurePosixPath(path).relative_to("src").with_suffix("").parts)


def blobs(repo, revision, paths):
    if not paths:
        return {}
    request = b"".join(f"{revision}:{path}".encode() + b"\0" for path in paths)
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
    sources = sorted(p for p in inventory if p.startswith("src/") and p.endswith(".lean"))
    declaration_paths = sorted(p for p in inventory if is_declaration(p))
    if any(inventory[p] not in {"100644", "100755"} for p in sources + declaration_paths):
        raise ValueError(f"{revision} contains a non-regular Lean source or dependency declaration")
    contents = blobs(repo, revision, sources + declaration_paths)
    manifests = {p: contents[p] for p in declaration_paths}
    edges = dependency_edges(manifests, inventory, revision=revision)
    files = []
    imports = {}
    modules = {module(path): path for path in sources}
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
            check=False,
        )
        if parsed.returncode:
            diagnostic = (parsed.stderr or parsed.stdout).strip().splitlines()
            detail = diagnostic[0] if diagnostic else f"exit status {parsed.returncode}"
            raise ValueError(f"cannot parse Lean headers at {revision}: {detail}")
        for path, line in zip(sources, parsed.stdout.splitlines(), strict=True):
            imports[path] = {modules[m] for m in json.loads(line) if m in modules}
            edges.setdefault(path, set()).update(imports[path])
    return modules, edges, imports


def plan(repo, base, head, lean, previous_failures=()):
    base, head = (
        git(repo, "rev-parse", "--verify", "--end-of-options", f"{ref}^{{commit}}").decode().strip()
        for ref in (base, head)
    )
    changed = names(git(repo, "diff", "--name-only", "--no-renames", "-z", base, head, "--"))
    if not changed and not previous_failures:
        return {"mode": "none", "changed": sorted(changed), "modules": []}
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

    retry = set(previous_failures) & set(new_modules.values())
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
        help="build these existing diagnostic files first, even if the new diff leaves them alone",
    )
    args = parser.parse_args(argv)
    try:
        result = plan(args.repo, args.base, args.head, args.lean, args.previous_failure)
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        result = {"mode": "full", "reason": str(error), "command": ["lake", "build"]}
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
