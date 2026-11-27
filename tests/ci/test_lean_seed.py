"""Exercise the filesystem boundary of the runner-local Lean dependency cache."""

import ast
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.ci import lean_seed
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
def test_elan_registry_is_private_and_existing_installations_are_preserved(tmp_path: Path) -> None:
    seed, home = tmp_path / "image", tmp_path / "home"
    installed = seed / ".elan/toolchains/leanprover--lean4---v4.37.0-rc1"
    (installed / "bin").mkdir(parents=True)
    (installed / "bin/lean").touch()
    link_toolchains(seed, home)
    registry = home / "toolchains"
    assert not registry.is_symlink()
    assert (registry / installed.name).resolve() == installed
    (registry / installed.name).unlink()
    (registry / "job-only").mkdir()
    link_toolchains(seed, home)
    assert list(registry.iterdir()) == [registry / "job-only"]
    assert not (installed.parent / "job-only").exists()


@pytest.mark.skipif(sys.platform != "linux", reason="Runner images use Linux directory symlinks")
@pytest.mark.parametrize("configured", [None, "", "/job/cache"])
def test_linked_toolchain_gets_a_writable_lake_cache(
    projects: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch, configured: str | None
) -> None:
    project, seed = projects
    installed = seed / ".elan/toolchains/leanprover--lean4---v4.37.0-rc1"
    (installed / "bin").mkdir(parents=True)
    (installed / "bin/lean").touch()
    output = project / "step.env"
    monkeypatch.setenv("GITHUB_ENV", str(output))
    if configured is None:
        monkeypatch.delenv("LAKE_CACHE_DIR", raising=False)
    else:
        monkeypatch.setenv("LAKE_CACHE_DIR", configured)

    elan_home = project / ".elan"
    assert restore(project, seed, elan_home)
    assert (elan_home / "toolchains" / installed.name).resolve() == installed
    if configured is None:
        assert output.read_text() == f"LAKE_CACHE_DIR={project / '.lake/cache'}\n"
    else:
        assert not output.exists()


@pytest.mark.skipif(sys.platform != "linux", reason="Runner images use Linux directory symlinks")
@pytest.mark.parametrize("registry", ["existing", "no seed toolchains"])
def test_lake_cache_is_left_alone_when_no_toolchain_was_linked(
    projects: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch, registry: str
) -> None:
    project, seed = projects
    elan_home = project / ".elan"
    if registry == "existing":
        installed = seed / ".elan/toolchains/leanprover--lean4---v4.37.0-rc1"
        (installed / "bin").mkdir(parents=True)
        (installed / "bin/lean").touch()
        (elan_home / "toolchains/job-only").mkdir(parents=True)
    output = project / "step.env"
    monkeypatch.setenv("GITHUB_ENV", str(output))
    monkeypatch.delenv("LAKE_CACHE_DIR", raising=False)

    assert restore(project, seed, elan_home)

    assert not output.exists()
    assert registry != "existing" or list((elan_home / "toolchains").iterdir()) == [elan_home / "toolchains/job-only"]


SEED_SCRIPT = Path(lean_seed.__file__)


def test_the_script_is_valid_for_every_python3_a_runner_may_have() -> None:
    """The action runs the runner's own `python3`, so the script must load before it can report a miss."""
    ast.parse(SEED_SCRIPT.read_text(encoding="utf-8"), feature_version=(3, 8))
    # `Path | None` is valid syntax everywhere but raises on 3.9 and older if the annotation is evaluated.
    assert all(isinstance(annotation, str) for annotation in restore.__annotations__.values())


@pytest.mark.parametrize("python", ["python3.8", "python3.9", "python3.10"])
def test_an_older_python3_reports_a_miss(projects: tuple[Path, Path], tmp_path: Path, python: str) -> None:
    project, seed = projects
    interpreter = shutil.which(python)
    if interpreter is None:
        pytest.skip(f"{python} is not installed")
    output = tmp_path / "output"

    completed = subprocess.run(
        [interpreter, "-I", str(SEED_SCRIPT), "--seed", str(seed), "--project", str(project), "--link-toolchains"],
        env=os.environ | {"GITHUB_OUTPUT": str(output), "ELAN_HOME": str(tmp_path / "elan")},
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert output.read_text() == "cache-hit=false\n"
    assert "tomllib" in completed.stdout


def test_a_python_without_tomllib_takes_normal_hydration_instead_of_failing_the_job(
    projects: tuple[Path, Path], tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Ubuntu 22.04's python3 is 3.10, which has no tomllib."""
    project, seed = projects
    output = tmp_path / "output"
    monkeypatch.setitem(sys.modules, "tomllib", None)
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    monkeypatch.setattr(sys, "argv", ["lean_seed.py", "--seed", str(seed), "--project", str(project)])

    lean_seed.main()

    assert output.read_text() == "cache-hit=false\n"
    assert "tomllib" in capsys.readouterr().out
    assert not (project / ".lake/packages").exists()
