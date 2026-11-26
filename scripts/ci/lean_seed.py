"""Restore prehydrated Lake dependencies from a trusted, runner-local checkout."""

import argparse
import json
import os
import re
import subprocess
import tempfile
import tomllib
from pathlib import Path


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
        isinstance(package, dict)
        and isinstance(package.get("name"), str)
        and re.fullmatch(r"[\w.-]+", package["name"])
        and package["name"] not in {".", ".."}
        and (seed / ".lake" / "packages" / package["name"] / ".git").is_dir()
        and package.get("type") == "git"
        and re.fullmatch("[a-fA-F0-9]{40}", str(package.get("rev")))
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
