"""Prove standard import-linter contracts against real package imports."""

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.parametrize("forbidden", [False, True])
def test_diagnostics_contract_detects_pytest_dependency(tmp_path: Path, forbidden: bool) -> None:
    root = Path(__file__).resolve().parents[2]
    shutil.copytree(root / "src/ci_esta", tmp_path / "ci_esta", ignore=shutil.ignore_patterns("__pycache__"))
    if forbidden:
        with (tmp_path / "ci_esta/diagnostics/__init__.py").open("a") as output:
            output.write("\nimport pytest\n")
    result = subprocess.run(
        [sys.executable, "-c", "from importlinter.cli import lint_imports_command; lint_imports_command()",
         "--config", str(root / "importlinter.toml"), "--no-cache"],
        cwd=tmp_path, env={**os.environ, "PYTHONPATH": str(tmp_path)},
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == int(forbidden), result.stdout + result.stderr
    assert ("2 kept, 0 broken" if not forbidden else "1 kept, 1 broken") in result.stdout
