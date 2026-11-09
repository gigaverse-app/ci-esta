"""The repository files a package is built from, as the real build tools report them.

A job that builds or installs the package needs to run when the package can change, not when the
documentation beside it does. Rather than re-implementing each build backend's inclusion rules, this
asks the tools: a Python wheel is built and its members mapped back to repository files, plus the
`readme` and license files `pyproject.toml` embeds in its metadata; an npm or Bun package is listed
with `npm pack --dry-run`. Anything the tools cannot answer raises, and the caller runs the package
jobs.
"""

from __future__ import annotations

import fnmatch
import json
import posixpath
import shutil
import subprocess
import tempfile
import tomllib
import zipfile
from pathlib import Path

from pytest_selective.impact_graph import within


class PackageInputsUnavailable(Exception):
    """The build tools could not list a package's inputs."""


def run(command: list[str], cwd: Path) -> str:
    try:
        return subprocess.run(
            command, cwd=cwd, check=True, capture_output=True, text=True, encoding="utf-8", errors="replace"
        ).stdout
    except (OSError, subprocess.CalledProcessError) as error:
        detail = (getattr(error, "stderr", "") or str(error)).strip().splitlines()
        raise PackageInputsUnavailable(f"{' '.join(command[:3])}: {detail[-1] if detail else error}") from error


def project_directory(manifest: str) -> str:
    return posixpath.dirname(manifest)


def python_inputs(repo: Path, manifest: str, files: set[str]) -> set[str]:
    """Files a wheel of this `pyproject.toml` is built from, plus the metadata files it embeds."""
    project = tomllib.loads((repo / manifest).read_text(encoding="utf-8")).get("project", {})
    directory = project_directory(manifest)
    local = sorted(path for path in files if within(path, directory or "."))
    uv = shutil.which("uv")
    if uv is None:
        raise PackageInputsUnavailable("uv is not installed")
    inputs = {manifest}
    with tempfile.TemporaryDirectory() as scratch:
        run([uv, "build", "--wheel", "--out-dir", scratch, directory or "."], repo)
        wheels = list(Path(scratch).glob("*.whl"))
        if len(wheels) != 1:
            raise PackageInputsUnavailable(f"{manifest}: expected one wheel, built {len(wheels)}")
        with zipfile.ZipFile(wheels[0]) as wheel:
            members = [name for name in wheel.namelist() if not name.split("/", 1)[0].endswith((".dist-info", ".data"))]
    for member in members:
        # An installed path is a suffix of its source path (src/ layouts, package-dir mappings).
        inputs.update(
            path for path in local if path == posixpath.join(directory, member) or path.endswith("/" + member)
        )
    readme = project.get("readme")
    if isinstance(readme, dict):
        readme = readme.get("file")
    if isinstance(readme, str):
        inputs.add(posixpath.join(directory, readme))
    license_value = project.get("license")
    if isinstance(license_value, dict) and isinstance(license_value.get("file"), str):
        inputs.add(posixpath.join(directory, license_value["file"]))
    for pattern in project.get("license-files", []):
        relative = [path[len(directory) + 1 :] if directory else path for path in local]
        inputs.update(posixpath.join(directory, path) for path in relative if fnmatch.fnmatchcase(path, pattern))
    return inputs & files | {manifest}


def node_inputs(repo: Path, manifest: str) -> set[str]:
    """Files `npm pack` would put in this package."""
    npm = shutil.which("npm")
    if npm is None:
        raise PackageInputsUnavailable("npm is not installed")
    directory = project_directory(manifest)
    listing = json.loads(run([npm, "pack", "--dry-run", "--json", "--ignore-scripts"], repo / directory) or "[]")
    return {posixpath.join(directory, entry["path"]) for package in listing for entry in package.get("files", [])}


def package_inputs(repo: Path, files: set[str]) -> dict[str, set[str]]:
    """Each buildable package manifest and the repository files its package is built from."""
    packages: dict[str, set[str]] = {}
    for manifest in sorted(files):
        name = posixpath.basename(manifest)
        if name == "pyproject.toml":
            document = tomllib.loads((repo / manifest).read_text(encoding="utf-8"))
            if "project" in document and "build-system" in document:
                packages[manifest] = python_inputs(repo, manifest, files)
        elif name == "package.json" and "node_modules/" not in manifest:
            document = json.loads((repo / manifest).read_text(encoding="utf-8"))
            if not document.get("private"):
                packages[manifest] = node_inputs(repo, manifest)
    return packages


def changed_package_inputs(repo: Path, files: set[str], changed: set[str]) -> list[str]:
    """Reasons a package changed: a changed input, or a deleted file beside one."""
    reasons = []
    for manifest, inputs in package_inputs(repo, files).items():
        reasons += [f"package input: {path} ({manifest})" for path in sorted(changed & inputs)]
        directories = {posixpath.dirname(path) for path in inputs}
        deleted = sorted(path for path in changed - files if posixpath.dirname(path) in directories)
        reasons += [f"package input deleted: {path} ({manifest})" for path in deleted]
    return reasons
