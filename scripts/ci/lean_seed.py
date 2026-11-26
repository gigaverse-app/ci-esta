"""Restore prehydrated Lake dependencies from a trusted, runner-local checkout."""

import argparse
import json
import os
import re
import subprocess
import tempfile
import tomllib
from pathlib import Path


def pinned_checkout(packages: Path, entry: object) -> bool:
    if not isinstance(entry, dict) or entry.get("type") != "git":
        return False
    name, revision = entry.get("name"), entry.get("rev")
    if not isinstance(name, str) or name in {".", ".."} or not re.fullmatch(r"[\w.-]+", name):
        return False
    if not isinstance(revision, str) or not re.fullmatch("[0-9a-f]{40}", revision):
        return False
    directory = packages / name
    if directory.is_symlink() or not (directory / ".git").is_dir():
        return False
    # The image builder owns these repositories. Trust only this specific read-only path.
    actual = subprocess.run(
        ["git", "-c", f"safe.directory={directory}", "-C", str(directory), "rev-parse", "--verify", "HEAD"],
        capture_output=True, text=True, check=False,
    )
    return actual.returncode == 0 and actual.stdout.strip() == revision


def matching_inputs(project: Path, seed: Path) -> bool:
    """Limit reuse to declarative projects with a pinned toolchain and Git dependencies."""
    files = ("lean-toolchain", "lakefile.toml", "lake-manifest.json")
    for root in (project, seed):
        if (root / "lakefile.lean").exists() or any(
            (root / name).is_symlink() or not (root / name).is_file() for name in files
        ):
            return False
    if any((project / name).read_bytes() != (seed / name).read_bytes() for name in files):
        return False
    toolchain = (project / "lean-toolchain").read_text().strip()
    if not re.fullmatch(r"leanprover/lean4:v\d+\.\d+\.\d+(?:-rc\d+)?", toolchain):
        return False
    config = tomllib.loads((project / "lakefile.toml").read_text(encoding="utf-8"))
    if config.get("packagesDir", ".lake/packages") != ".lake/packages" or config.get(
        "manifestFile", "lake-manifest.json"
    ) != "lake-manifest.json":
        return False
    manifest = json.loads((project / "lake-manifest.json").read_bytes())
    if not isinstance(manifest, dict) or manifest.get("packagesDir") != ".lake/packages":
        return False
    packages = manifest.get("packages")
    return isinstance(packages, list) and bool(packages) and all(
        pinned_checkout(seed / ".lake" / "packages", package)
        for package in packages
    )


def restore(project: Path, seed: Path) -> bool:
    # Resolve 'current' once so switching to a new immutable seed cannot mix revisions.
    seed = seed.resolve()
    lake = project / ".lake"
    packages = lake / "packages"
    if lake.is_symlink() or os.path.lexists(packages) or not matching_inputs(project, seed):
        return False
    source = seed / ".lake" / "packages"
    if not source.is_dir() or source.is_symlink():
        return False
    lake.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(dir=lake) as staging:
        staged = Path(staging) / "packages"
        # Reflinks share data blocks, never writable inodes. Copy normally on other filesystems.
        subprocess.run(
            ["cp", "-R", "--reflink=auto", "--preserve=mode,timestamps,links", "--", str(source), str(staged)],
            check=True,
        )
        staged.rename(packages)
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, default=Path.cwd())
    parser.add_argument("--seed", type=Path, required=True)
    args = parser.parse_args()
    try:
        hit = restore(args.project, args.seed)
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        print(f"Lake dependency seed unavailable: {error}")
        hit = False
    result = str(hit).lower()
    print(f"Restored Lake dependency seed: {result}")
    with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as output:
        output.write(f"cache-hit={result}\n")


if __name__ == "__main__":
    main()
