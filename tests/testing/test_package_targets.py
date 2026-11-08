"""Jobs that build the package run when the package's inputs change, on real Git commits and real builds."""

import shutil
import subprocess
from pathlib import Path

import pytest
from pytest_selective.ci import Lane, LaneConfig
from pytest_selective.impact_graph import policy_fingerprints
from pytest_selective.impact_models import GitTree, ImpactConfig

from ci_esta.testing.work_plan import plan_work
from tests.testing.git_repo import commit, write

CI = """\
name: CI
on: [pull_request]
jobs:
  select-tests:
    runs-on: ubuntu-latest
    outputs:
      lanes: ${{ steps.plan.outputs.lanes }}
    steps:
      - id: plan
        uses: gigaverse-app/ci-esta/actions/plan-work@v1
        with:
          config: .github/test-lanes.json
  unit:
    needs: select-tests
    if: ${{ fromJSON(needs.select-tests.outputs.lanes).unit }}
    runs-on: ubuntu-latest
    steps:
      - run: pytest tests
  build:
    needs: select-tests
    if: ${{ fromJSON(needs.select-tests.outputs.lanes).package }}
    runs-on: ubuntu-latest
    steps:
      - run: {build}
"""
PYPROJECT = """\
[build-system]
requires = ["hatchling"]
build-backend = "{backend}"

[project]
name = "sample"
version = "1.0.0"
readme = "README.md"
license-files = ["LICENSE"]

[tool.hatch.build.targets.wheel]
packages = ["src/sample"]
"""


def lanes() -> LaneConfig:
    return LaneConfig(
        graph=ImpactConfig(module_roots=["src", "."], test_roots=["tests"]),
        # A lane needs roots or inputs; the package lane's inputs come from the build itself.
        lanes={"unit": Lane(roots=["tests"]), "package": Lane(inputs=["pyproject.toml"])},
    )


def reviewed(repo: Path, config: LaneConfig) -> LaneConfig:
    """Record the fixture's reviewed pytest policy, as an adopter does with `pytest-selective fingerprints`."""
    listing = subprocess.run(
        ["git", "-C", str(repo), "ls-tree", "-r", "HEAD"], capture_output=True, text=True, check=True
    )
    files = {line.split("	", 1)[1]: line.split()[2] for line in listing.stdout.splitlines()}
    tree = GitTree(tree="HEAD", files=files, links=[])
    graph = config.graph.model_copy(update={"pytest_policy": policy_fingerprints(repo, tree)})
    return config.model_copy(update={"graph": graph})


def repository(tmp_path: Path, *, build: str) -> None:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    write(tmp_path, ".github/workflows/ci.yml", CI.replace("{build}", build))
    write(tmp_path, ".github/test-lanes.json", lanes().model_dump_json())


@pytest.fixture
def python_package(tmp_path: Path) -> tuple[Path, str]:
    repository(tmp_path, build="uv build && uvx twine check --strict dist/*")
    write(tmp_path, "pyproject.toml", PYPROJECT.format(backend="hatchling.build"))
    write(tmp_path, "src/sample/__init__.py", "from sample.value import VALUE\n")
    write(tmp_path, "src/sample/value.py", "VALUE = 1\n")
    write(tmp_path, "src/sample/extra.py", "EXTRA = 1\n")
    write(tmp_path, "tests/test_value.py", "from sample.value import VALUE\ndef test_value(): assert VALUE\n")
    write(tmp_path, "tests/test_other.py", "def test_other(): assert True\n")
    write(tmp_path, "README.md", "# Sample\n")
    write(tmp_path, "LICENSE", "Apache-2.0\n")
    write(tmp_path, "docs/guide.md", "# Guide\n")
    return tmp_path, commit(tmp_path)


uv = pytest.mark.skipif(shutil.which("uv") is None, reason="needs uv to build the wheel")


@uv
@pytest.mark.parametrize(
    ("path", "content", "expected"),
    [
        # The wheel's metadata embeds the README and the license.
        ("README.md", "# Changed\n", {"unit": False, "package": True}),
        ("LICENSE", "MIT\n", {"unit": False, "package": True}),
        # Documentation the build does not include selects nothing.
        ("docs/guide.md", "# Changed\n", {"unit": False, "package": False}),
        # Package sources run the tests that import them and the build.
        ("src/sample/value.py", "VALUE = 2\n", {"unit": True, "package": True}),
        # Tests are not in the wheel.
        (
            "tests/test_value.py",
            "from sample.value import VALUE\ndef test_value(): assert VALUE == 1\n",
            {"unit": True, "package": False},
        ),
    ],
)
def test_a_changed_package_input_runs_the_build(python_package, path, content, expected):
    repo, base = python_package
    write(repo, path, content)
    result = plan_work(repo, reviewed(repo, lanes()), base, commit(repo))
    assert result.lanes == expected, result.lane_reasons


@uv
def test_a_deleted_package_file_runs_the_build(python_package):
    repo, base = python_package
    (repo / "src/sample/extra.py").unlink()
    result = plan_work(repo, reviewed(repo, lanes()), base, commit(repo))
    assert result.lanes["package"] is True
    assert "package input deleted: src/sample/extra.py (pyproject.toml)" in result.lane_reasons["package"]


@uv
def test_evidence_names_the_input_and_the_manifest(python_package):
    repo, base = python_package
    write(repo, "README.md", "# Changed\n")
    result = plan_work(repo, reviewed(repo, lanes()), base, commit(repo))
    assert result.lane_reasons["package"] == ["package input: README.md (pyproject.toml)"]


@uv
def test_a_package_that_cannot_be_built_runs_the_build(python_package):
    repo, _ = python_package
    write(repo, "pyproject.toml", PYPROJECT.format(backend="no_such_backend.build"))
    base = commit(repo)
    write(repo, "docs/guide.md", "# Changed\n")
    result = plan_work(repo, reviewed(repo, lanes()), base, commit(repo))
    assert result.lanes["package"] is True
    assert result.lane_reasons["package"][0].startswith("full-suite fallback: package inputs unavailable")


@pytest.mark.skipif(shutil.which("npm") is None, reason="needs npm to list the package")
@pytest.mark.parametrize(
    ("path", "expected"),
    [("lib/index.js", True), ("README.md", True), ("docs/guide.md", False), ("scripts/release.js", False)],
)
def test_an_npm_package_is_listed_by_npm_pack(tmp_path, path, expected):
    repository(tmp_path, build="npm pack")
    write(tmp_path, "package.json", '{"name": "sample", "version": "1.0.0", "files": ["lib"]}\n')
    write(tmp_path, "lib/index.js", "module.exports = 1;\n")
    write(tmp_path, "README.md", "# Sample\n")
    write(tmp_path, "docs/guide.md", "# Guide\n")
    write(tmp_path, "scripts/release.js", "console.log('release');\n")
    base = commit(tmp_path)
    write(tmp_path, path, "// changed\n")
    config = lanes().model_copy(update={"lanes": {"package": Lane(inputs=["pyproject.toml"])}})
    result = plan_work(tmp_path, reviewed(tmp_path, config), base, commit(tmp_path))
    assert result.lanes == {"package": expected}, result.lane_reasons
