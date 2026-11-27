"""Restore prehydrated Lake dependencies from a trusted, runner-local checkout."""

# The action runs this with the runner's own python3. Annotations stay unevaluated so that one older
# than 3.10, which cannot evaluate `Path | None`, still loads the script and reports a miss.
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import tempfile
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
    # Imported here so a runner whose python3 predates 3.11 reports a miss instead of failing the job.
    import tomllib

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


def restore(project: Path, seed: Path, elan_home: Path | None = None) -> bool:
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
        subprocess.check_call(
            ["cp", "-R", "--reflink=auto", "--preserve=mode,timestamps,links", "--", str(source), str(staged)],
        )
        staged.rename(packages)
    if elan_home is not None:
        try:
            # Decide where the cache goes before linking, so a toolchain is never linked without one.
            lake_cache = lake_cache_setting(project)
            if link_toolchains(seed, elan_home) and lake_cache:
                with Path(os.environ["GITHUB_ENV"]).open("a", encoding="utf-8") as output:
                    output.write(lake_cache)
        except (OSError, ValueError) as error:
            print(f"Elan will install the requested toolchain normally: {error}")
    return True


def lake_cache_setting(project: Path) -> str:
    """The GITHUB_ENV line keeping Lake's artifact writes outside a linked, read-only toolchain; empty if set."""
    if "LAKE_CACHE_DIR" in os.environ:
        return ""
    if not os.environ.get("GITHUB_ENV"):
        raise ValueError("a linked toolchain requires GITHUB_ENV or an explicit LAKE_CACHE_DIR")
    directory = str(project.resolve() / ".lake" / "cache")
    if "\n" in directory or "\r" in directory:
        raise ValueError("Lake cache path must fit on one line")
    return f"LAKE_CACHE_DIR={directory}\n"


def link_toolchains(seed: Path, elan_home: Path) -> bool:
    """Offer installed toolchains by Elan's own names in a fresh, job-private registry; True if any was linked."""
    installed = seed / ".elan" / "toolchains"
    registry = elan_home / "toolchains"
    if not installed.is_dir() or os.path.lexists(registry):
        return False
    linked = False
    elan_home.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=elan_home) as staging:
        staged = Path(staging) / "toolchains"
        staged.mkdir()
        for toolchain in installed.iterdir():
            if (toolchain / "bin" / "lean").is_file():
                (staged / toolchain.name).symlink_to(toolchain, target_is_directory=True)
                linked = True
        staged.rename(registry)
    return linked


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, default=Path.cwd())
    parser.add_argument("--seed", type=Path, required=True)
    parser.add_argument("--link-toolchains", action="store_true")
    args = parser.parse_args()
    elan_home = Path(os.environ.get("ELAN_HOME") or Path.home() / ".elan") if args.link_toolchains else None
    try:
        hit = restore(args.project, args.seed, elan_home)
    except (OSError, ValueError, RuntimeError, ImportError, subprocess.CalledProcessError) as error:
        print(f"Lake dependency seed unavailable: {error}")
        hit = False
    result = str(hit).lower()
    print(f"Restored Lake dependency seed: {result}")
    with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as output:
        output.write(f"cache-hit={result}\n")


if __name__ == "__main__":
    main()
