"""Exercise the shipped lane config on committed real Git changes."""
import subprocess
from pathlib import Path

import pytest
from pytest_selective.ci import LaneConfig, plan

from tests.testing.git_repo import commit, write

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("path, expected", [
    ("action.yml", True), ("setup-cached-uv/action.yml", True),
    ("actions/setup-cached-uv/action.yml", True),
    ("actions/setup-cached-uv/helper.py", True),
        ("README.md", False), ("docs/critical-path.md", False),
    (".github/workflows/observe-ci.yml", False), (".github/pull_request_template.md", False),
    ("src/example.py", True), ("tests/test_example.py", True), ("scripts/ci/setup.py", True),
    ("uv.lock", True), ("importlinter.toml", True), (".github/workflows/ci.yml", True),
    (".github/actions/setup-cached-uv/action.yml", True),
])
def test_repository_lane_inputs(tmp_path, path, expected):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    write(tmp_path, "pyproject.toml", (ROOT / "pyproject.toml").read_text())
    write(tmp_path, "src/example.py", "VALUE = 1")
    write(tmp_path, "tests/test_example.py", "from example import VALUE\ndef test_value(): assert VALUE")
    base = commit(tmp_path)
    write(tmp_path, path, "# change\n")
    head = commit(tmp_path)
    config = LaneConfig.model_validate_json((ROOT / ".github/test-lanes.json").read_text())
    assert plan(tmp_path, config, base, head).lanes["tests"] is expected
    assert plan(tmp_path, config, "f" * 40, head).lanes["tests"] is True
