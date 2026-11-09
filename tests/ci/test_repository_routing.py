"""Exercise the shipped lane config on committed real Git changes."""
# gv:test-dependency: .github/test-lanes.json
# gv:test-dependency: .github/workflows/ci.yml
# gv:test-dependency: .github/workflows/public-actions.yml
import subprocess
from contextlib import closing
from pathlib import Path

import pytest
from pytest_selective.ci import LaneConfig
from pytest_selective.impact_graph import GraphCache
from pytest_selective.impact_selection import affected

from ci_esta.testing.work_plan import plan_work as plan
from tests.testing.git_repo import commit, write

ROOT = Path(__file__).resolve().parents[2]


DOCS_ONLY = ["README.md", "docs/critical-path.md", "documentation/requirements.txt", "documentation/requirements.in",
             "examples/pytest-shards/README.md", "actions/service-container/README.md", "mkdocs.yml",
             ".readthedocs.yaml", "CHANGELOG.md", ".github/pull_request_template.md"]


def committed_changes(tmp_path: Path, *paths: str) -> tuple[str, str]:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    write(tmp_path, "pyproject.toml", (ROOT / "pyproject.toml").read_text())
    write(tmp_path, "src/example.py", "VALUE = 1")
    write(tmp_path, "tests/test_example.py", "from example import VALUE\ndef test_value(): assert VALUE")
    # A second test keeps a one-test change from counting as "all graph test files affected".
    write(tmp_path, "tests/test_other.py", "def test_other(): pass")
    for path in paths:
        if path.startswith(".github/workflows/"):
            write(tmp_path, path, (ROOT / path).read_text())
    base = commit(tmp_path)
    for path in paths:
        content = (ROOT / path).read_text() if path.startswith(".github/workflows/") else ""
        write(tmp_path, path, content + "\n# change\n")
    head = commit(tmp_path)
    return base, head


def lanes_for(tmp_path: Path, *paths: str) -> dict[str, bool]:
    base, head = committed_changes(tmp_path, *paths)
    config = LaneConfig.model_validate_json((ROOT / ".github/test-lanes.json").read_text())
    assert all(plan(tmp_path, config, "f" * 40, head).lanes.values())
    return plan(tmp_path, config, base, head).lanes


@pytest.mark.parametrize("path, tests, package", [
    ("action.yml", True, True),
    ("actions/setup-cached-uv/action.yml", True, True),
    ("actions/setup-cached-uv/helper.py", True, True),
    ("actions/new-action/index.ts", True, True),
    ("actions/new-action/extensionless", True, True),
    ("actions/new-action/nested/helper.py", True, True),
    ("examples/nested/project/bun.lock", True, True),
    ("examples/nested/project/README.md", False, False),
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


@pytest.mark.parametrize("path, expected", [
    ("docs/critical-path.md", []),
    ("src/example.py", ["tests/test_example.py"]),
    ("scripts/ci/setup.py", ["tests/test_example.py", "tests/test_other.py"]),
    (".github/workflows/ci.yml", ["tests/test_example.py", "tests/test_other.py"]),
])
def test_file_plan_narrows_source_and_preserves_execution_inputs(tmp_path, path, expected):
    base, head = committed_changes(tmp_path, path)
    config = LaneConfig.model_validate_json((ROOT / ".github/test-lanes.json").read_text()).file_config()
    with closing(GraphCache(tmp_path / "cache.sqlite3")) as cache:
        assert affected(tmp_path, base, head, config, cache).selected == expected
