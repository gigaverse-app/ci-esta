"""Whole-lane planning through the workflow graph, on real Git commits."""

import json
import subprocess
from pathlib import Path

import pytest
from pytest_selective.ci import Lane, LaneConfig
from pytest_selective.impact_models import ImpactConfig

from ci_esta.testing.work_plan import main, plan_work
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
      - uses: actions/checkout@v7
      - id: plan
        uses: gigaverse-app/ci-esta/actions/plan-work@v1
        with:
          config: .github/test-lanes.json
  lint:
    runs-on: ubuntu-latest
    steps:
      - run: ruff check .
  unit:
    needs: select-tests
    if: ${{ fromJSON(needs.select-tests.outputs.lanes).unit }}
    runs-on: ubuntu-latest
    steps:
      - uses: ./.github/actions/setup
      - run: python scripts/run_unit.py
  live:
    needs: select-tests
    if: ${{ fromJSON(needs.select-tests.outputs.lanes)['live'] }}
    uses: ./.github/workflows/live.yml
"""
LIVE = """\
on: workflow_call
jobs:
  run:
    runs-on: ubuntu-latest
    steps:
      - run: bash scripts/live_helper.sh tests/live
"""
SETUP = """\
runs:
  using: composite
  steps:
    - shell: bash
      run: bash "${{ github.action_path }}/install.sh"
"""


def lanes_config(**overrides: object) -> LaneConfig:
    return LaneConfig(
        graph=ImpactConfig(module_roots=["src", "."], test_roots=["tests"]),
        lanes={"unit": Lane(roots=["tests/unit"]), "live": Lane(roots=["tests/live"])},
        **overrides,
    )


@pytest.fixture
def repository(tmp_path: Path) -> tuple[Path, str]:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    write(tmp_path, "src/sample/__init__.py")
    write(tmp_path, "src/sample/value.py", "VALUE = 1\n")
    write(tmp_path, "tests/unit/test_value.py", "from sample.value import VALUE\ndef test_value(): assert VALUE\n")
    write(tmp_path, "tests/live/test_other.py", "def test_other(): assert True\n")
    write(tmp_path, "README.md", "# Sample\n")
    write(tmp_path, ".github/workflows/ci.yml", CI)
    write(tmp_path, ".github/workflows/live.yml", LIVE)
    write(tmp_path, ".github/actions/setup/action.yml", SETUP)
    write(tmp_path, ".github/actions/setup/install.sh", "pip install .\n")
    write(tmp_path, ".github/actions/setup/README.md", "Sets up Python.\n")
    write(tmp_path, ".github/PULL_REQUEST_TEMPLATE.md", "## Summary\n")
    write(tmp_path, ".github/dependabot.yml", "version: 2\n")
    write(tmp_path, ".github/test-lanes.json", lanes_config().model_dump_json())
    write(tmp_path, "scripts/run_unit.py", "print('unit')\n")
    write(tmp_path, "scripts/live_helper.sh", 'pytest "$1"\n')
    return tmp_path, commit(tmp_path)


def change(repo: Path, path: str, old: str | None = None, new: str = "# changed\n") -> str:
    target = repo / path
    if old is None:
        write(repo, path, (target.read_text(encoding="utf-8") if target.exists() else "") + new)
    else:
        text = target.read_text(encoding="utf-8")
        assert old in text
        write(repo, path, text.replace(old, new))
    return commit(repo)


@pytest.mark.parametrize(
    ("path", "old", "new", "expected"),
    [
        # Documentation and repository settings no job executes select nothing.
        ("README.md", None, "More.\n", {"unit": False, "live": False}),
        (".github/PULL_REQUEST_TEMPLATE.md", None, "More.\n", {"unit": False, "live": False}),
        (".github/dependabot.yml", None, "# weekly\n", {"unit": False, "live": False}),
        (".github/actions/setup/README.md", None, "More.\n", {"unit": False, "live": False}),
        # A job that gates no lane always runs; editing it selects nothing.
        (".github/workflows/ci.yml", "ruff check .", "ruff check src", {"unit": False, "live": False}),
        # A gated job selects the lanes its condition reads.
        (
            ".github/workflows/ci.yml",
            "python scripts/run_unit.py",
            "python -X dev scripts/run_unit.py",
            {"unit": True, "live": False},
        ),
        # Files a gated job executes, directly or through an action or a reusable workflow.
        ("scripts/run_unit.py", None, "# changed\n", {"unit": True, "live": False}),
        (".github/actions/setup/install.sh", None, "# changed\n", {"unit": True, "live": False}),
        (".github/actions/setup/action.yml", None, "# changed\n", {"unit": True, "live": False}),
        ("scripts/live_helper.sh", None, "# changed\n", {"unit": False, "live": True}),
        (
            ".github/workflows/live.yml",
            "runs-on: ubuntu-latest",
            "runs-on: ubuntu-24.04",
            {"unit": False, "live": True},
        ),
        # The planner and its configuration reach every lane.
        (".github/test-lanes.json", None, "\n", {"unit": True, "live": True}),
        (
            ".github/workflows/ci.yml",
            "actions/checkout@v7\n      - id: plan",
            "actions/checkout@v7\n        with: {fetch-depth: 0}\n      - id: plan",
            {"unit": True, "live": True},
        ),
        # Settings outside jobs reach every lane the workflow runs.
        (".github/workflows/ci.yml", "on: [pull_request]", "on: [pull_request, push]", {"unit": True, "live": True}),
        # Python changes still go through pytest-selective's import graph.
        ("src/sample/value.py", "VALUE = 1", "VALUE = 2", {"unit": True, "live": False}),
    ],
)
def test_changes_reach_lanes_through_the_workflow_graph(repository, path, old, new, expected):
    repo, base = repository
    head = change(repo, path, old, new)
    result = plan_work(repo, lanes_config(), base, head)
    assert result.lanes == expected, result.lane_reasons


def test_evidence_names_the_job_and_the_file(repository):
    repo, base = repository
    head = change(repo, ".github/actions/setup/install.sh")
    result = plan_work(repo, lanes_config(), base, head)
    assert result.lane_reasons["unit"] == [
        "workflow input: .github/actions/setup/install.sh (run by .github/workflows/ci.yml#unit)"
    ]


def test_an_unreadable_workflow_runs_every_lane(repository):
    repo, base = repository
    head = change(repo, ".github/workflows/ci.yml", "jobs:", "jobs: [unclosed")
    result = plan_work(repo, lanes_config(), base, head)
    assert result.lanes == {"unit": True, "live": True}
    assert result.reason.startswith("full-suite fallback")


def test_explicit_global_inputs_are_kept_exactly(repository):
    repo, base = repository
    head = change(repo, ".github/workflows/ci.yml", "ruff check .", "ruff check src")
    result = plan_work(repo, lanes_config(global_inputs=[".github/workflows/ci.yml"]), base, head)
    assert result.lanes == {"unit": True, "live": True}


def test_a_new_workflow_that_runs_no_lane_selects_nothing(repository):
    repo, base = repository
    head = change(
        repo,
        ".github/workflows/docs.yml",
        None,
        "on: push\njobs:\n  docs:\n    runs-on: x\n    steps: [{run: mkdocs build}]\n",
    )
    assert plan_work(repo, lanes_config(), base, head).lanes == {"unit": False, "live": False}


def test_cli_writes_lane_outputs(repository, tmp_path_factory, capsys):
    repo, base = repository
    head = change(repo, "scripts/run_unit.py")
    output = tmp_path_factory.mktemp("output") / "github_output"
    config = repo / ".github/test-lanes.json"
    assert (
        main(
            [
                "--repo",
                str(repo),
                "--config",
                str(config),
                "--base",
                base,
                "--head",
                head,
                "--github-output",
                str(output),
            ]
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out)["lanes"] == {"unit": True, "live": False}
    assert 'lanes={"unit": true, "live": false}' in output.read_text(encoding="utf-8")
