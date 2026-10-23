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


def test_private_sync_credentials_use_process_memory_and_preserve_existing_git_config(cache, monkeypatch, tmp_path):
    import subprocess
    monkeypatch.setenv("CI_ESTA_GIT_TOKEN", "test-only-not-a-real-token")
    monkeypatch.setenv("GIT_CONFIG_COUNT", "1")
    monkeypatch.setenv("GIT_CONFIG_KEY_0", "core.autocrlf")
    monkeypatch.setenv("GIT_CONFIG_VALUE_0", "false")
    env = cache.sync_environment()
    assert env['GIT_CONFIG_KEY_0'] == 'core.autocrlf'
    assert env['GIT_CONFIG_COUNT'] == '3'
    # Exercise Git's real credential protocol; no network request is made.
    credential = subprocess.run(['git', 'credential', 'fill'],
        input='protocol=https\nhost=github.com\n\n', env=env, cwd=tmp_path,
        text=True, capture_output=True, check=True)
    assert 'password=test-only-not-a-real-token' in credential.stdout
    assert all('test-only-not-a-real-token' not in value for key, value in env.items()
               if key.startswith('GIT_CONFIG_'))
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("case", ["valid", "drift", "broken-output"])
def test_cache_measurement_is_written_only_after_real_locked_sync(tmp_path, case):
    import os
    import subprocess

    project = tmp_path / "pyproject.toml"
    project.write_text('[project]\nname="cache-control"\nversion="1.0"\nrequires-python=">=3.11"\n')
    env = {key: value for key, value in os.environ.items() if key not in {"UV_PROJECT_ENVIRONMENT", "VIRTUAL_ENV"}}
    env.update(UV_OFFLINE="1", CACHE_WORKING_DIRECTORY=str(tmp_path), CACHE_SYNC_ARGS="")
    subprocess.run(["uv", "lock", "--python", sys.executable], cwd=tmp_path, env=env, check=True, capture_output=True)
    if case == "drift":
        project.write_text(project.read_text().replace('version="1.0"', 'version="2.0"'))
    output = tmp_path if case == "broken-output" else tmp_path / "outputs"
    result = subprocess.run([sys.executable, str(SCRIPT.resolve()), "sync"],
                            env={**env, "GITHUB_OUTPUT": str(output)}, text=True, capture_output=True)
    if case == "drift":
        assert result.returncode != 0
        assert not output.exists()
    else:
        assert result.returncode == 0, result.stderr
        if case == "broken-output":
            assert "Cache measurement unavailable" in result.stdout
        else:
            outputs = dict(line.split("=", 1) for line in output.read_text().splitlines())
            assert outputs["restored-usable"] == "false"
            assert float(outputs["sync-seconds"]) > 0
