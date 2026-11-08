"""Lanes inferred from the workflow, planned end to end with no lane file, on real Git commits."""

import json
import subprocess
from pathlib import Path

import pytest

from ci_esta.testing.lane_inference import infer_lanes
from ci_esta.testing.work_plan import main
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
  lint:
    runs-on: ubuntu-latest
    steps:
      - run: ruff check .
  unit:
    needs: select-tests
    if: ${{ fromJSON(needs.select-tests.outputs.lanes).unit }}
    runs-on: ubuntu-latest
    steps:
      - run: uv run --no-sync pytest tests/unit -q --junitxml=report.xml
  live:
    needs: select-tests
    if: ${{ fromJSON(needs.select-tests.outputs.lanes).live }}
    runs-on: ubuntu-latest
    steps:
      - run: python -m pytest -m live tests/live
  wrapped:
    needs: select-tests
    if: ${{ fromJSON(needs.select-tests.outputs.lanes).wrapped }}
    runs-on: ubuntu-latest
    steps:
      - run: python scripts/run_tests.py
  smoke:
    needs: select-tests
    if: ${{ fromJSON(needs.select-tests.outputs.lanes).smoke }}
    runs-on: ubuntu-latest
    steps:
      - run: bash scripts/smoke.sh
"""
PYPROJECT = '[project]\nname = "sample"\nversion = "1"\n\n[tool.pytest.ini_options]\ntestpaths = ["tests"]\n'


@pytest.fixture
def repository(tmp_path: Path) -> tuple[Path, str]:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    write(tmp_path, ".github/workflows/ci.yml", CI)
    write(tmp_path, "pyproject.toml", PYPROJECT)
    write(tmp_path, "src/sample/__init__.py")
    write(tmp_path, "src/sample/value.py", "VALUE = 1\n")
    write(tmp_path, "tests/unit/test_value.py", "from sample.value import VALUE\ndef test_value(): assert VALUE\n")
    write(tmp_path, "tests/live/test_live.py", "def test_live(): assert True\n")
    write(tmp_path, "tests/live/README.md", "# Live checks\n")
    write(tmp_path, "scripts/run_tests.py", "import pytest; pytest.main()\n")
    write(tmp_path, "scripts/smoke.sh", "echo smoke\n")
    write(tmp_path, "README.md", "# Sample\n")
    return tmp_path, commit(tmp_path)


def test_lanes_and_roots_come_from_the_test_commands(repository):
    repo, base = repository
    config = infer_lanes(repo, base, base)
    assert {name: lane.roots for name, lane in config.lanes.items()} == {
        "live": ["tests/live"],
        "smoke": [],
        "unit": ["tests/unit"],
        # A test-runner script collects pytest's testpaths.
        "wrapped": ["tests"],
    }
    # A lane without tests is selected through the jobs it gates.
    assert config.lanes["smoke"].inputs == [".github/workflows/ci.yml#smoke"]


def plan(repo: Path, base: str, head: str, capsys) -> dict[str, bool]:
    assert main(["--repo", str(repo), "--base", base, "--head", head]) == 0
    return json.loads(capsys.readouterr().out)["lanes"]


@pytest.mark.parametrize(
    ("path", "content", "expected"),
    [
        ("README.md", "# Changed\n", {"live": False, "smoke": False, "unit": False, "wrapped": False}),
        (
            "tests/live/test_live.py",
            "def test_live(): assert 1\n",
            {"live": True, "smoke": False, "unit": False, "wrapped": True},
        ),
        ("src/sample/value.py", "VALUE = 2\n", {"live": False, "smoke": False, "unit": True, "wrapped": True}),
        ("scripts/smoke.sh", "echo changed\n", {"live": False, "smoke": True, "unit": False, "wrapped": False}),
    ],
)
def test_a_repository_without_a_lane_file_plans_its_lanes(repository, capsys, path, content, expected):
    repo, base = repository
    write(repo, path, content)
    assert plan(repo, base, commit(repo), capsys) == expected


def test_changing_how_pytest_collects_runs_every_lane(repository, capsys):
    repo, base = repository
    write(repo, "pyproject.toml", PYPROJECT.replace('testpaths = ["tests"]', 'testpaths = ["tests"]\naddopts = "-x"'))
    assert set(plan(repo, base, commit(repo), capsys).values()) == {True}


def test_a_workflow_that_reads_no_lane_asks_for_a_lane_file(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    write(
        tmp_path, ".github/workflows/ci.yml", "on: push\njobs:\n  test:\n    runs-on: x\n    steps: [{run: pytest}]\n"
    )
    base = commit(tmp_path)
    with pytest.raises(ValueError, match="add a lane file"):
        infer_lanes(tmp_path, base, base)
