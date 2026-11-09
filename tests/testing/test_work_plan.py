"""Whole-lane planning through the workflow graph, on real Git commits."""

import json
import subprocess
from pathlib import Path

import pytest
from pytest_selective.ci import Lane, LaneConfig
from pytest_selective.impact_graph import DependencyDeclarationError
from pytest_selective.impact_models import ImpactConfig

from ci_esta.testing.lane_inference import resolve
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


DIRECTORIES = """\
name: CI
on: [pull_request]
defaults:
  run:
    working-directory: tools
jobs:
  select-tests:
    runs-on: ubuntu-latest
    outputs:
      lanes: ${{ steps.plan.outputs.lanes }}
    steps:
      - id: plan
        uses: gigaverse-app/ci-esta/actions/plan-work@v1
  dogfood:
    needs: select-tests
    if: ${{ fromJSON(needs.select-tests.outputs.lanes).unit }}
    runs-on: ubuntu-latest
    steps:
      - uses: ./
  smoke:
    needs: select-tests
    if: ${{ fromJSON(needs.select-tests.outputs.lanes).live }}
    runs-on: ubuntu-latest
    defaults:
      run:
        working-directory: smoke
    steps:
      - run: bash check.sh
      - run: python ../scripts/install_check.py
        working-directory: tools
"""
ROOT_ACTION = """\
runs:
  using: composite
  steps:
    - shell: bash
      run: bash "${{ github.action_path }}/scripts/install.sh"
"""


@pytest.fixture
def directories(repository: tuple[Path, str]) -> tuple[Path, str]:
    """The root action, working directories and declared reads, on top of the repository fixture."""
    repo, _ = repository
    write(repo, ".github/workflows/ci.yml", DIRECTORIES)
    write(repo, "action.yml", ROOT_ACTION)
    write(repo, "scripts/install.sh", "pip install .\n")
    write(repo, "smoke/check.sh", "echo ok\n")
    write(repo, "smoke/README.md", "# Smoke\n")
    write(repo, "tools/README.md", "# Tools\n")
    # A script reads files by path; declarations say which, in pytest-selective's syntax, transitively.
    write(repo, "scripts/install_check.py", "# gv:test-dependency: scripts/install.sh\nprint('check')\n")
    write(repo, "scripts/install.sh", "# gv:test-dependency: config/*.toml\npip install .\n")
    write(repo, "config/settings.toml", "debug = false\n")
    return repo, commit(repo)


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        # `uses: ./` runs the repository's own action and the files it executes.
        ("action.yml", {"unit": True, "live": False}),
        # A path relative to the step's working directory, set by the job or the step.
        ("smoke/check.sh", {"unit": False, "live": True}),
        ("scripts/install_check.py", {"unit": False, "live": True}),
        # Declared reads, followed through the declared file's own declarations.
        ("scripts/install.sh", {"unit": True, "live": True}),
        ("config/settings.toml", {"unit": True, "live": True}),
        # A file nothing executes or declares, even inside a working directory, selects nothing.
        ("smoke/README.md", {"unit": False, "live": False}),
        ("tools/README.md", {"unit": False, "live": False}),
    ],
)
def test_root_action_working_directories_and_declared_reads(directories, path, expected):
    repo, base = directories
    head = change(repo, path)
    assert plan_work(repo, lanes_config(), base, head).lanes == expected


def test_an_invalid_declaration_is_an_error_not_a_full_run(directories):
    repo, base = directories
    # A shell script: pytest-selective's own graph reads declarations only in Python files.
    head = change(repo, "smoke/check.sh", new="# gv:test-dependency: missing/*.json\n")
    with pytest.raises(DependencyDeclarationError, match="matches no tracked files"):
        plan_work(repo, lanes_config(), base, head)


LOCAL_PLANNER = """\
name: CI
on: [pull_request]
jobs:
  select-tests:
    runs-on: ubuntu-latest
    outputs:
      lanes: ${{ steps.plan.outputs.lanes }}
    steps:
      - id: plan
        uses: ./actions/plan-lanes
  distributions:
    needs: select-tests
    if: ${{ fromJSON(needs.select-tests.outputs.lanes).package }}
    runs-on: ubuntu-latest
    steps:
      - run: uv build
      - if: ${{ fromJSON(needs.select-tests.outputs.lanes).tests }}
        run: python scripts/smoke.py dist
"""


def test_a_local_planning_action_makes_its_job_the_planner_and_steps_do_not_widen_package_lanes(tmp_path):
    from ci_esta.workflow_graph import ALL, WorkflowGraph

    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    write(tmp_path, ".github/workflows/ci.yml", LOCAL_PLANNER)
    write(
        tmp_path,
        "actions/plan-lanes/action.yml",
        "runs:\n  using: composite\n  steps:\n    - shell: bash\n      run: python -m pytest_selective.ci --base x\n",
    )
    write(tmp_path, "scripts/smoke.py", "print('smoke')\n")
    graph = WorkflowGraph(tmp_path, commit(tmp_path))
    assert graph.jobs[(".github/workflows/ci.yml", "select-tests")].lanes == {ALL}
    # The job-level condition decides when the package is built; the smoke step's condition is its own.
    assert graph.jobs[(".github/workflows/ci.yml", "distributions")].lanes == {"package", "tests"}
    assert graph.package_lanes() == {"package"}


ENTRIES = """\
name: CI
on: [pull_request]
jobs:
  select-tests:
    runs-on: ubuntu-latest
    outputs:
      lanes: ${{ steps.plan.outputs.lanes }}
    steps:
      - id: plan
        uses: ./actions/plan
  unit:
    needs: select-tests
    if: ${{ fromJSON(needs.select-tests.outputs.lanes).unit }}
    runs-on: ubuntu-latest
    steps:
      - run: python -m sample.report --check
      - run: bash scripts/runtime.sh sample.wrapped
  live:
    needs: select-tests
    if: ${{ fromJSON(needs.select-tests.outputs.lanes).live }}
    runs-on: ubuntu-latest
    steps:
      # Smoke-testing the planning action does not make this job the planner.
      - uses: ./actions/plan
      - uses: ./actions/runner
      - run: sample-cli lanes
"""
PLAN_ACTION = """\
runs:
  using: composite
  steps:
    - shell: bash
      run: python -m pytest_selective.ci --base x
"""
RUNNER_ACTION = """\
runs:
  using: composite
  steps:
    - shell: bash
      env:
        SHARED_ACTION_PATH: ${{ github.action_path }}
      run: |
        PY=$(bash "$SHARED_ACTION_PATH/../../scripts/runtime.sh")
        "$PY" -m sample.runner
"""


@pytest.fixture
def entries(tmp_path: Path) -> tuple[Path, str]:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    write(tmp_path, ".github/workflows/ci.yml", ENTRIES)
    write(tmp_path, "actions/plan/action.yml", PLAN_ACTION)
    write(tmp_path, "actions/runner/action.yml", RUNNER_ACTION)
    write(tmp_path, "scripts/runtime.sh", "echo python3\n")
    write(
        tmp_path,
        "pyproject.toml",
        '[project]\nname = "sample"\nversion = "1"\n[project.scripts]\nsample-cli = "sample.cli:main"\n',
    )
    write(tmp_path, "src/sample/__init__.py")
    write(tmp_path, "src/sample/report.py", "from sample.format import render\n")
    write(tmp_path, "src/sample/format.py", "def render(): pass\n")
    write(tmp_path, "src/sample/runner.py", "from sample.engine import run\n")
    write(tmp_path, "src/sample/engine.py", "def run(): pass\n")
    write(tmp_path, "src/sample/cli.py", "from sample.commands import main\n")
    write(tmp_path, "src/sample/commands.py", "def main(): pass\n")
    write(tmp_path, "src/sample/unused.py", "VALUE = 1\n")
    write(tmp_path, "src/sample/wrapped.py", "from sample.deep import VALUE\n")
    write(tmp_path, "src/sample/deep.py", "VALUE = 1\n")
    write(tmp_path, "tests/unit/test_nothing.py", "def test_nothing(): pass\n")
    write(tmp_path, "tests/live/test_nothing_else.py", "def test_nothing_else(): pass\n")
    return tmp_path, commit(tmp_path)


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        # `python -m sample.report` depends on what that module imports.
        ("src/sample/format.py", {"unit": True, "live": False}),
        # `"$PY" -m sample.runner`, in an action that names its own directory through `env`.
        ("src/sample/engine.py", {"unit": False, "live": True}),
        ("scripts/runtime.sh", {"unit": True, "live": True}),
        # A module name a wrapper script receives as an argument.
        ("src/sample/deep.py", {"unit": True, "live": False}),
        # A console script of the repository runs its module.
        ("src/sample/commands.py", {"unit": False, "live": True}),
        # Package code no job runs and no test imports selects nothing.
        ("src/sample/unused.py", {"unit": False, "live": False}),
    ],
)
def test_jobs_depend_on_the_python_modules_they_run(entries, path, expected):
    repo, base = entries
    head = change(repo, path)
    resolved = resolve(repo, base, head, None)
    result = plan_work(repo, resolved.config, base, head, rules=resolved.rules)
    assert result.lanes == expected, result.lane_reasons


def test_the_planner_is_the_job_whose_lanes_others_read(entries):
    from ci_esta.workflow_graph import ALL, WorkflowGraph

    repo, base = entries
    graph = WorkflowGraph(repo, base)
    assert graph.jobs[(".github/workflows/ci.yml", "select-tests")].lanes == {ALL}
    assert graph.jobs[(".github/workflows/ci.yml", "live")].lanes == {"live"}


@pytest.mark.parametrize(
    "condition",
    [
        "${{ fromJSON(needs.select-tests.outputs.lanes).unit }}",
        "${{ fromJSON(needs.select-tests.outputs.lanes)['unit'] }}",
        "${{ fromJSON(needs.select-tests.outputs.lanes || '{}').unit }}",
        "${{ toJSON(fromJSON(needs.select-tests.outputs.lanes || \"{}\").unit) != 'false' }}",
    ],
)
def test_a_lane_is_read_with_or_without_a_fallback(condition):
    from ci_esta.workflow_graph import lane_references

    assert lane_references(condition) == {"unit"}
    assert lane_references(condition, "select-tests") == {"unit"}
    assert lane_references(condition, "other") == set()
