import importlib.util
import sys
from pathlib import Path

import pytest

SCRIPT = Path("scripts/ci/environment_cache.py")


@pytest.fixture
def cache():
    spec = importlib.util.spec_from_file_location("environment_cache", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_identity_changes_with_every_install_contract_input(cache, tmp_path):
    base = dict(manifests="lock-a", sync_args="--all-groups", root=tmp_path, variant="linux")
    original = cache.identity(**base)
    for field, value in [("manifests", "lock-b"), ("sync_args", "--only-group lint"),
                         ("root", tmp_path / "workspace"), ("variant", "macos")]:
        assert cache.identity(**(base | {field: value})) != original
    assert cache.identity(**base) == original


def test_missing_and_broken_environment_are_recoverable(cache, tmp_path):
    assert not cache.validate(tmp_path)
    venv = tmp_path / ".venv"
    venv.mkdir()
    (venv / "broken").write_text("stale")
    assert not cache.validate(tmp_path)
    assert not venv.exists()


def test_valid_environment_is_preserved(cache, tmp_path):
    import subprocess
    subprocess.run([sys.executable, "-m", "venv", "--without-pip", str(tmp_path / ".venv")], check=True)
    assert cache.validate(tmp_path)
    assert (tmp_path / ".venv").exists()


def test_external_symlink_is_removed_without_touching_its_target(cache, tmp_path):
    target = tmp_path / "outside"
    target.mkdir()
    (target / "keep").write_text("valuable")
    root = tmp_path / "project"
    root.mkdir()
    (root / ".venv").symlink_to(target, target_is_directory=True)
    assert not cache.validate(root)
    assert (target / "keep").read_text() == "valuable"


def test_missing_manifests_and_unlocked_install_modes_are_rejected(cache, tmp_path):
    with pytest.raises(ValueError):
        cache.identity(manifests="", sync_args="", root=tmp_path, variant="")
    for args in ("--no-editable", "--frozen", "--project elsewhere", "--directory elsewhere"):
        with pytest.raises(ValueError):
            cache.sync_arguments(args)
