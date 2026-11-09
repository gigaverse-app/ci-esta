"""Lanes inferred from the workflow, planned end to end with no lane file, on real Git commits."""

import json
import subprocess
from pathlib import Path

import pytest

from ci_esta.cli import main as cli
from ci_esta.testing.lane_inference import infer_lanes, resolve
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
    with pytest.raises(ValueError, match="name lanes in a lane file"):
        infer_lanes(tmp_path, base, base)


def lane_file(repo: Path, document: dict) -> Path:
    path = repo.parent / f"{repo.name}-lanes.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


def test_a_lane_file_that_extends_the_workflow_changes_only_what_it_names(repository):
    repo, base = repository
    extends = lane_file(
        repo,
        {
            "extends": "workflow",
            "lanes": {"live": {"roots": ["tests/live/test_live.py"]}, "docs": {"inputs": ["docs/**"]}},
        },
    )
    resolved = resolve(repo, base, base, extends)
    roots = {name: lane.roots for name, lane in resolved.config.lanes.items()}
    assert roots["live"] == ["tests/live/test_live.py"]  # overridden
    assert roots["unit"] == ["tests/unit"]  # still inferred
    assert resolved.config.lanes["docs"].inputs == ["docs/**"]  # added
    assert resolved.sources["live"] == [f"overridden by {extends.as_posix()}"]
    assert resolved.sources["docs"] == [f"added by {extends.as_posix()}"]
    assert resolved.sources["unit"] == [
        "roots tests/unit from .github/workflows/ci.yml#unit: `uv run --no-sync pytest tests/unit -q --junitxml=report.xml`"
    ]


def test_a_complete_lane_file_is_used_as_written(repository):
    repo, base = repository
    complete = lane_file(
        repo, {"graph": {"module_roots": ["src", "."], "test_roots": ["tests"]}, "lanes": {"all": {"roots": ["tests"]}}}
    )
    resolved = resolve(repo, base, base, complete)
    assert list(resolved.config.lanes) == ["all"]
    assert resolved.sources == {"all": [f"lane file {complete.as_posix()}"]}


def test_an_extending_lane_file_rejects_unknown_keys(repository):
    repo, base = repository
    with pytest.raises(ValueError, match="unknown keys"):
        resolve(repo, base, base, lane_file(repo, {"extends": "workflow", "lane": {}}))


def test_ci_esta_lanes_shows_and_explains_the_lanes(repository, capsys):
    repo, base = repository
    write(repo, "scripts/smoke.sh", "echo changed\n")
    head = commit(repo)
    assert cli(["lanes", "--repo", str(repo)]) == 0
    listing = capsys.readouterr().out
    assert "| `smoke` | – | smoke | no test command; selected through .github/workflows/ci.yml#smoke |" in listing
    assert cli(["lanes", "--repo", str(repo), "--base", base, "--head", head]) == 0
    explained = capsys.readouterr().out
    assert (
        "| `smoke` | ✅ runs | workflow input: scripts/smoke.sh (run by .github/workflows/ci.yml#smoke) |" in explained
    )
    assert "| `unit` | ⏭️ skipped | no affected tests or changed inputs |" in explained


def test_ci_esta_lanes_writes_a_lane_file_to_start_from(repository, tmp_path_factory):
    repo, base = repository
    target = tmp_path_factory.mktemp("out") / "test-lanes.json"
    assert cli(["lanes", "--repo", str(repo), "--write", str(target)]) == 0
    written = json.loads(target.read_text(encoding="utf-8"))
    assert written["extends"] == "workflow"
    assert written["lanes"]["unit"] == {"roots": ["tests/unit"]}
    # The written file plans exactly like the workflow it came from.
    assert resolve(repo, base, base, target).config.lanes == infer_lanes(repo, base, base).lanes


def test_the_plan_appends_a_readable_step_summary(repository, tmp_path_factory, capsys):
    repo, base = repository
    write(repo, "README.md", "# Changed\n")
    head = commit(repo)
    summary = tmp_path_factory.mktemp("summary") / "summary.md"
    assert main(["--repo", str(repo), "--base", base, "--head", head, "--summary", str(summary)]) == 0
    capsys.readouterr()
    text = summary.read_text(encoding="utf-8")
    assert text.startswith("### Lane selection")
    assert "| `unit` | ⏭️ skipped |" in text


def plan_with(repo: Path, base: str, path: str, content: str, document: dict, capsys) -> dict:
    extends = lane_file(repo, {"extends": "workflow", **document})
    write(repo, path, content)
    head = commit(repo)
    assert main(["--repo", str(repo), "--config", str(extends), "--base", base, "--head", head]) == 0
    return json.loads(capsys.readouterr().out)


def test_a_rule_selects_a_lane_when_its_files_change(repository, capsys):
    repo, base = repository
    rule = {"name": "schemas", "when": ["schemas/**"], "select": ["lane:live"], "reason": "loaded by name"}
    result = plan_with(repo, base, "schemas/user.json", "{}", {"rules": [rule]}, capsys)
    assert result["lanes"] == {"live": True, "smoke": False, "unit": False, "wrapped": False}
    assert result["lane_reasons"]["live"] == ["rule schemas: schemas/user.json (loaded by name)"]


def test_a_rule_can_select_the_lanes_a_job_runs(repository, capsys):
    repo, base = repository
    rule = {"name": "smoke-data", "when": ["fixtures/*.csv"], "select": ["job:.github/workflows/ci.yml#smoke"]}
    result = plan_with(repo, base, "fixtures/rows.csv", "a,b\n", {"rules": [rule]}, capsys)
    assert result["lanes"] == {"live": False, "smoke": True, "unit": False, "wrapped": False}


def test_the_python_environment_rule_names_itself_and_can_be_narrowed(repository, capsys):
    repo, base = repository
    default = plan_with(repo, base, "requirements-docs.txt", "mkdocs\n", {}, capsys)
    assert set(default["lanes"].values()) == {True}
    assert "rule python-environment: requirements-docs.txt" in default["lane_reasons"]["unit"]
    narrowed = {"name": "python-environment", "when": ["pyproject.toml", "uv.lock"], "select": ["all"]}
    result = plan_with(repo, base, "requirements-docs.txt", "mkdocs==2\n", {"rules": [narrowed]}, capsys)
    assert set(result["lanes"].values()) == {False}


def test_a_built_in_rule_can_be_switched_off(repository, capsys):
    repo, base = repository
    result = plan_with(
        repo, base, "requirements-docs.txt", "mkdocs\n", {"disable_rules": ["python-environment"]}, capsys
    )
    assert set(result["lanes"].values()) == {False}


@pytest.mark.parametrize(
    ("document", "message"),
    [
        ({"disable_rules": ["no-such-rule"]}, "disable_rules names no rule"),
        ({"rules": [{"name": "a", "when": ["x"], "select": ["all"]}] * 2}, "named more than once"),
        ({"rules": [{"name": "a", "when": ["x"], "select": ["everything"]}]}, "use all, package"),
    ],
)
def test_invalid_rules_are_reported(repository, document, message):
    repo, base = repository
    with pytest.raises(ValueError, match=message):
        resolve(repo, base, base, lane_file(repo, {"extends": "workflow", **document}))


def test_ci_esta_lanes_lists_the_rules_in_force(repository, capsys):
    repo, base = repository
    extends = lane_file(
        repo, {"extends": "workflow", "rules": [{"name": "schemas", "when": ["schemas/**"], "select": ["lane:live"]}]}
    )
    assert cli(["lanes", "--repo", str(repo), "--config", str(extends)]) == 0
    listing = capsys.readouterr().out
    assert "| `python-environment` | pyproject.toml<br>**/pyproject.toml<br>uv.lock<br>… " in listing
    assert "| `bun-environment` |" in listing
    assert "| `schemas` | schemas/** | lane:live | lane file |" in listing


JAVASCRIPT = """\
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
  counter:
    needs: select-tests
    if: ${{ fromJSON(needs.select-tests.outputs.lanes).counter }}
    runs-on: ubuntu-latest
    defaults:
      run:
        working-directory: counter
    steps:
      - run: node --test
  viewer:
    needs: select-tests
    if: ${{ fromJSON(needs.select-tests.outputs.lanes).viewer }}
    runs-on: ubuntu-latest
    steps:
      - run: node --test viewer/diff.test.mjs
  web:
    needs: select-tests
    if: ${{ fromJSON(needs.select-tests.outputs.lanes).web }}
    runs-on: ubuntu-latest
    steps:
      - run: npm ci && npm test
        working-directory: web
      - run: npx jest tests --ci
        working-directory: web
  unit:
    needs: select-tests
    if: ${{ fromJSON(needs.select-tests.outputs.lanes).unit }}
    runs-on: ubuntu-latest
    steps:
      - run: pytest
        working-directory: service
"""


def test_javascript_runners_and_working_directories_give_roots(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    write(tmp_path, ".github/workflows/ci.yml", JAVASCRIPT)
    for path in ("counter/test/tally.test.js", "viewer/diff.test.mjs", "web/tests/app.test.js"):
        write(tmp_path, path, "// test\n")
    write(tmp_path, "service/tests/test_app.py", "def test_app(): pass\n")
    base = commit(tmp_path)
    config = infer_lanes(tmp_path, base, base)
    assert {name: lane.roots for name, lane in config.lanes.items()} == {
        # A runner with no path collects the tests under its working directory.
        "counter": ["counter"],
        # A named test file, from the repository root.
        "viewer": ["viewer/diff.test.mjs"],
        # `npm test` in a package directory, and a path relative to the step's working directory.
        "web": ["web", "web/tests"],
        # pytest with no path in a working directory collects that directory.
        "unit": ["service"],
    }


COMMANDS = """\
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
  adopter:
    needs: select-tests
    if: ${{ fromJSON(needs.select-tests.outputs.lanes).adopter }}
    runs-on: ubuntu-latest
    steps:
      - uses: ./test
        with:
          working-directory: examples/adopter
  demo:
    needs: select-tests
    if: ${{ fromJSON(needs.select-tests.outputs.lanes).demo }}
    runs-on: ubuntu-latest
    steps:
      - run: cd demos/shop && pytest -q
      - run: uv run --directory demos/blog pytest tests
      - run: demos/saleor/run.sh -n 4
  upstream:
    needs: select-tests
    if: ${{ fromJSON(needs.select-tests.outputs.lanes).upstream }}
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v7
        with:
          repository: example/other
          path: .upstream/other
      - run: pytest
        working-directory: .upstream/other
      - uses: gigaverse-app/ci-esta/actions/pytest-shards@v1
        with:
          pytest-command: pytest package/tests
  bun:
    needs: select-tests
    if: ${{ fromJSON(needs.select-tests.outputs.lanes).bun }}
    runs-on: ubuntu-latest
    steps:
      - uses: gigaverse-app/ci-esta/actions/run-bun-tests@v1
        with:
          inventory: inventory.json
"""
TEST_ACTION = """\
inputs:
  working-directory:
    default: "."
runs:
  using: composite
  steps:
    - shell: bash
      working-directory: ${{ inputs.working-directory }}
      run: uv run pytest -m due_work
"""


@pytest.fixture
def commands(tmp_path: Path) -> tuple[Path, str]:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    write(tmp_path, ".github/workflows/ci.yml", COMMANDS)
    write(tmp_path, "test/action.yml", TEST_ACTION)
    # A nested project: its own pyproject, a src layout, and tests importing it by name.
    write(tmp_path, "package/pyproject.toml", '[project]\nname = "kit"\nversion = "1"\n')
    write(tmp_path, "package/src/kit/__init__.py")
    write(tmp_path, "package/src/kit/core.py", "VALUE = 1\n")
    write(tmp_path, "package/tests/test_core.py", "from kit.core import VALUE\ndef test_core(): assert VALUE\n")
    for path in ("examples/adopter", "demos/shop", "demos/blog/tests", "demos/saleor"):
        write(tmp_path, f"{path}/test_it.py", "def test_it(): pass\n")
    write(
        tmp_path, "demos/saleor/run.sh", '#!/usr/bin/env bash\n# Runs pytest.\nexec "$VENV/bin/python" -m pytest "$@"\n'
    )
    write(tmp_path, "web/sum.test.ts", "// test\n")
    return tmp_path, commit(tmp_path)


def test_roots_come_from_actions_scripts_and_directories(commands):
    repo, base = commands
    config = infer_lanes(repo, base, base)
    assert {name: lane.roots for name, lane in config.lanes.items()} == {
        # A local composite action's step, with the caller's input filled in.
        "adopter": ["examples/adopter"],
        # `cd DIR &&`, `uv run --directory DIR`, and a shell script's own pytest, which collects its directory.
        "demo": ["demos/blog/tests", "demos/saleor", "demos/shop"],
        # Commands in another repository's checkout are left out; a command-valued action input counts.
        "upstream": ["package/tests"],
        # An action that runs the repository's Bun tests from an inventory.
        "bun": ["."],
    }
    # A nested project's src layout resolves its imports.
    assert config.graph.module_roots[:2] == ["package/src", "package"]


def test_a_nested_src_layout_reaches_its_tests(commands, capsys):
    repo, base = commands
    write(repo, "package/src/kit/core.py", "VALUE = 2\n")
    lanes = plan(repo, base, commit(repo), capsys)
    assert lanes["upstream"] is True
    assert lanes["demo"] is False


def test_an_extending_lane_file_can_start_a_workflow_without_lane_conditions(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    write(
        tmp_path, ".github/workflows/ci.yml", "on: push\njobs:\n  test:\n    runs-on: x\n    steps: [{run: pytest}]\n"
    )
    write(tmp_path, "tests/test_it.py", "def test_it(): pass\n")
    base = commit(tmp_path)
    resolved = resolve(
        tmp_path, base, base, lane_file(tmp_path, {"extends": "workflow", "lanes": {"unit": {"roots": ["tests"]}}})
    )
    assert resolved.config.lanes["unit"].roots == ["tests"]
    assert resolved.sources["unit"][0].startswith("added by ")


@pytest.mark.parametrize("base", ["", "0000000000000000000000000000000000000000"])
def test_a_missing_base_runs_every_lane(repository, capsys, base):
    repo, head = repository
    assert main(["--repo", str(repo), "--base", base, "--head", head]) == 0
    result = json.loads(capsys.readouterr().out)
    assert set(result["lanes"].values()) == {True}
    assert result["reason"] == "full run: no base commit to compare against"


def test_ci_esta_lanes_reports_errors_without_a_traceback(tmp_path, capsys):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    write(tmp_path, ".github/workflows/ci.yml", "on: push\njobs:\n  test:\n    runs-on: x\n    steps: []\n")
    commit(tmp_path)
    assert cli(["lanes", "--repo", str(tmp_path)]) == 2
    assert "no job condition reads a lane" in capsys.readouterr().err


@pytest.mark.parametrize(
    "command",
    [
        "uv run --locked pytest-selective execute-plan -- -q -n 4 --junitxml=junit.xml",
        "pytest-selective run --config .github/test-impact.json -- -q",
    ],
)
def test_pytest_selective_runners_collect_pytests_testpaths(tmp_path, command):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    write(tmp_path, ".github/workflows/ci.yml", CI.replace("python scripts/run_tests.py", command))
    write(tmp_path, ".github/test-impact.json", "{}")
    write(tmp_path, "pyproject.toml", PYPROJECT)
    write(tmp_path, "tests/unit/test_value.py", "def test_value(): pass\n")
    write(tmp_path, "scripts/smoke.sh", "echo smoke\n")
    base = commit(tmp_path)
    assert infer_lanes(tmp_path, base, base).lanes["wrapped"].roots == ["tests"]


def test_a_base_missing_from_history_runs_every_lane(repository, capsys):
    repo, head = repository
    assert main(["--repo", str(repo), "--base", "1234567890abcdef1234567890abcdef12345678", "--head", head]) == 0
    result = json.loads(capsys.readouterr().out)
    assert set(result["lanes"].values()) == {True}
    assert "is not in this checkout's history" in result["reason"]


def test_a_pull_request_merge_is_planned_against_the_base_it_was_built_on(repository, capsys):
    """GitHub merges the PR head into the base branch's current tip, which can be ahead of `base.sha`."""
    repo, base = repository

    def run(*args: str) -> str:
        return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True).stdout

    run("checkout", "-q", "-b", "feature")
    write(repo, "tests/live/test_live.py", "def test_live(): assert 1\n")
    pr_head = commit(repo, "the pull request")
    run("checkout", "-q", "-")
    write(repo, "scripts/smoke.sh", "echo landed on main meanwhile\n")
    commit(repo, "another merge on main")
    run("-c", "user.name=Test", "-c", "user.email=test@example.com", "merge", "-q", "--no-ff", "-m", "merge", pr_head)
    head = run("rev-parse", "HEAD").strip()

    assert main(["--repo", str(repo), "--base", base, "--head", head, "--pr-head", pr_head]) == 0
    tested = json.loads(capsys.readouterr().out)["lanes"]
    assert tested == {"live": True, "smoke": False, "unit": False, "wrapped": True}
    # Without the PR head, main's own change reads as the PR's: the smoke lane runs too.
    assert plan(repo, base, head, capsys)["smoke"] is True
