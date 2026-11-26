"""Exercise the filesystem boundary of the runner-local Lean dependency cache."""

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.ci.lean_seed import link_toolchains, restore


@pytest.fixture
def projects(tmp_path: Path) -> tuple[Path, Path]:
    seed = tmp_path / "image"
    seed.mkdir()
    (seed / "lean-toolchain").write_text("leanprover/lean4:v4.37.0-rc1\n")
    (seed / "lakefile.toml").write_text('name = "Example"\n')
    dep = seed / ".lake/packages/mathlib"
    dep.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(dep)], check=True)
    subprocess.run(["git", "-C", str(dep), "-c", "user.name=Image Builder", "-c", "user.email=builder@example.test",
                    "-c", "commit.gpgsign=false", "commit", "-q", "--allow-empty", "-m", "package"], check=True)
    revision = subprocess.check_output(["git", "-C", str(dep), "rev-parse", "HEAD"], text=True).strip()
    (seed / "lake-manifest.json").write_text(json.dumps({
        "packagesDir": ".lake/packages", "packages": [{"type": "git", "name": "mathlib", "rev": revision}]
    }))
    project = tmp_path / "job"
    shutil.copytree(seed, project, ignore=shutil.ignore_patterns(".lake"))
    (dep / "Example.olean").write_bytes(b"trusted")
    return project, seed


@pytest.mark.skipif(sys.platform != "linux", reason="GNU cp and the runner image are Linux-specific")
def test_matching_seed_creates_a_private_writable_copy(projects: tuple[Path, Path]) -> None:
    project, seed = projects
    assert restore(project, seed)
    rel = ".lake/packages/mathlib/Example.olean"
    (project / rel).write_bytes(b"job")
    assert (seed / rel).read_bytes() == b"trusted"
    assert not restore(project, seed)
    assert (project / rel).read_bytes() == b"job"


@pytest.mark.parametrize("name", ["lean-toolchain", "lakefile.toml", "lake-manifest.json"])
def test_changed_inputs_require_normal_hydration(projects: tuple[Path, Path], name: str) -> None:
    project, seed = projects
    with (project / name).open("a") as changed:
        changed.write("\n")
    assert not restore(project, seed)
    assert not (project / ".lake/packages").exists()


@pytest.mark.parametrize("kind", ["missing", "path dependency", "missing package", "wrong revision", "dynamic config"])
def test_unsupported_inputs_require_normal_hydration(projects: tuple[Path, Path], kind: str) -> None:
    project, seed = projects
    if kind == "missing":
        seed = seed / "absent"
    elif kind == "path dependency":
        for root in (project, seed):
            manifest = root / "lake-manifest.json"
            manifest.write_text(manifest.read_text().replace('"git"', '"path"'))
    elif kind == "missing package":
        (seed / ".lake/packages/mathlib").rename(seed / ".lake/packages/absent")
    elif kind == "wrong revision":
        for root in (project, seed):
            manifest = root / "lake-manifest.json"
            data = json.loads(manifest.read_text())
            data["packages"][0]["rev"] = "a" * 40
            manifest.write_text(json.dumps(data))
    else:
        (project / "lakefile.lean").touch()
    assert not restore(project, seed)
    assert not (project / ".lake/packages").exists()


def test_interrupted_copy_leaves_no_partial_packages(
    projects: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    project, seed = projects

    def interrupt(args: list[str]) -> None:
        Path(args[-1]).mkdir()
        raise subprocess.CalledProcessError(1, args)

    monkeypatch.setattr(subprocess, "check_call", interrupt)
    with pytest.raises(subprocess.CalledProcessError):
        restore(project, seed)
    assert list((project / ".lake").iterdir()) == []

@pytest.mark.skipif(sys.platform != "linux", reason="Runner images use Linux directory symlinks")
@pytest.mark.parametrize("configured_cache", ["", "/custom/lake-cache"])
def test_elan_registry_is_private_and_existing_installations_are_preserved(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, configured_cache: str
) -> None:
    seed, home = tmp_path / "image", tmp_path / "home"
    installed = seed / ".elan/toolchains/leanprover--lean4---v4.37.0-rc1"
    (installed / "bin").mkdir(parents=True)
    (installed / "bin/lean").touch()
    github_env = tmp_path / "job-env"
    github_env.touch()
    monkeypatch.setenv("GITHUB_ENV", str(github_env))
    monkeypatch.setenv("LAKE_CACHE_DIR", configured_cache)
    cache = tmp_path / "job/.lake/cache"
    link_toolchains(seed, home, cache)
    assert github_env.read_text() == ("" if configured_cache else f"LAKE_CACHE_DIR={cache}\n")
    registry = home / "toolchains"
    assert not registry.is_symlink()
    assert (registry / installed.name).resolve() == installed
    (registry / installed.name).unlink()
    (registry / "job-only").mkdir()
    link_toolchains(seed, home, cache)
    assert list(registry.iterdir()) == [registry / "job-only"]
    assert not (installed.parent / "job-only").exists()
