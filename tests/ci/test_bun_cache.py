import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path("scripts/ci/bun_cache.py").resolve()


@pytest.mark.skipif(shutil.which("bun") is None, reason="real Bun required; public-action smoke also exercises this")
def test_locked_install_runs_on_warm_cache_and_propagates_install_failure(tmp_path):
    package = tmp_path / "package.json"
    local = tmp_path / "local-package"
    local.mkdir()
    (local / "package.json").write_text(json.dumps({"name": "local-package", "version": "1.0.0"}))
    package.write_text(json.dumps({"name": "cache-smoke", "dependencies": {"local-package": "file:./local-package"}}))
    subprocess.run(["bun", "install"], cwd=tmp_path, check=True, capture_output=True)
    output = tmp_path / "outputs"
    env = {**os.environ, "GITHUB_OUTPUT": str(output), "BUN_WORKING_DIRECTORY": str(tmp_path)}
    for _ in range(2):
        subprocess.run([sys.executable, str(SCRIPT), "sync"], env=env, check=True, capture_output=True)
    assert "seconds=" in output.read_text()
    (tmp_path / "bun.lock").write_text("invalid lockfile")
    failed = subprocess.run([sys.executable, str(SCRIPT), "sync"], env=env, capture_output=True, text=True)
    assert failed.returncode != 0
    assert "lockfile" in failed.stderr.lower()


def test_missing_lockfile_fails_before_cache_identity_is_published(tmp_path):
    output = tmp_path / "outputs"
    result = subprocess.run([sys.executable, str(SCRIPT), "identity"], capture_output=True, env={
        **os.environ, "GITHUB_OUTPUT": str(output), "BUN_WORKING_DIRECTORY": str(tmp_path),
        "BUN_CACHE_PREFIX": "test-", "BUN_CACHE_INPUTS": "hash",
    })
    assert result.returncode != 0
    assert not output.exists()
