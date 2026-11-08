"""Exercise the shipped lane config on committed real Git changes."""
import subprocess
from pathlib import Path

import pytest
from pytest_selective.ci import LaneConfig, plan

from tests.testing.git_repo import commit, write

ROOT = Path(__file__).resolve().parents[2]


DOCS_ONLY = ["README.md", "docs/critical-path.md", "documentation/requirements.txt", "documentation/requirements.in",
             "examples/pytest-shards/README.md", "actions/service-container/README.md", "mkdocs.yml",
             ".readthedocs.yaml", "CHANGELOG.md", ".github/pull_request_template.md"]


def lanes_for(tmp_path: Path, *paths: str) -> dict[str, bool]:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    write(tmp_path, "pyproject.toml", (ROOT / "pyproject.toml").read_text())
    write(tmp_path, "src/example.py", "VALUE = 1")
    write(tmp_path, "tests/test_example.py", "from example import VALUE\ndef test_value(): assert VALUE")
    # A second test keeps a one-test change from counting as "all graph test files affected".
    write(tmp_path, "tests/test_other.py", "def test_other(): pass")
    base = commit(tmp_path)
    for path in paths:
        write(tmp_path, path, "# change\n")
    head = commit(tmp_path)
    config = LaneConfig.model_validate_json((ROOT / ".github/test-lanes.json").read_text())
    assert all(plan(tmp_path, config, "f" * 40, head).lanes.values())
    return plan(tmp_path, config, base, head).lanes


@pytest.mark.parametrize("path, tests, package", [
    ("action.yml", True, True),
    ("actions/setup-cached-uv/action.yml", True, True),
    ("actions/setup-cached-uv/helper.py", True, True),
    ("actions/new-action/index.ts", True, True),
    ("actions/new-action/extensionless", True, True),
    ("actions/README.md", True, False),
    ("actions/service-container/README.md", False, False),
    ("examples/gigaverse-ci-drill.yaml", True, True),
    ("examples/bun-cache/.bun-version", True, True),
    ("examples/bun-cache/bun.lock", True, True),
    ("examples/pytest-shards/README.md", False, False),
    ("README.md", False, True), ("LICENSE", False, True), ("docs/critical-path.md", False, False),
    ("documentation/requirements.txt", False, False), ("documentation/requirements.in", False, False),
    ("mkdocs.yml", False, False), (".readthedocs.yaml", False, False),
    (".github/workflows/observe-ci.yml", False, False), (".github/pull_request_template.md", False, False),
    ("src/example.py", True, True), ("tests/test_example.py", True, False), ("scripts/ci/setup.py", True, True),
    ("uv.lock", True, True), ("importlinter.toml", True, True), (".github/workflows/ci.yml", True, True),
    ("src/ci_esta/testing/bun/selection.py", True, True),
    ("actions/resolve-lane-evidence/merged.cjs", True, True),
    ("src/helpers.ts", True, True),
    ("tests/github_actions/future.test.mjs", True, False),
    ("tests/github_actions/future.test.cjs", True, False),
    ("scripts/ci/helper.ts", True, True),
    (".github/workflows/public-actions.yml", True, True),
    (".github/validation-inputs.json", True, True),
])
def test_repository_lane_inputs(tmp_path, path, tests, package):
    assert lanes_for(tmp_path, path) == {"tests": tests, "package": package}


def test_documentation_only_commit_selects_no_tests(tmp_path):
    """README.md is the packaged long description, so only metadata checks may run."""
    assert lanes_for(tmp_path, *DOCS_ONLY) == {"tests": False, "package": True}
    assert lanes_for(tmp_path / "prose", *(path for path in DOCS_ONLY if path != "README.md")) == {
        "tests": False, "package": False}
