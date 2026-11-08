"""Adoption advice reads actual workflow wiring without executing consumer code."""

import json
import subprocess
import sys
from pathlib import Path


def audit(root: Path, *args: str) -> dict:
    result = subprocess.run(
        [sys.executable, "-m", "ci_esta.cli", "adoption", "--root", str(root), "--json", *args],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def write(root: Path, path: str, content: str) -> None:
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content)


def test_report_discovers_missing_feedback_and_does_not_enable_retention(tmp_path):
    write(tmp_path, ".github/workflows/tests.yml", """
jobs:
  tests:
    steps:
      - uses: gigaverse-app/pytest-selective/actions/test-impact@v1
        with:
          full: "${{ github.event_name == 'schedule' }}"
      - uses: gigaverse-app/ci-esta/actions/learn-test-timings@v1
      - run: pytest -q
""")
    before = list(tmp_path.rglob("*"))
    report = audit(tmp_path)
    assert {item["id"] for item in report["suggestions"]} >= {"checkpoint-policy", "timing-feedback", "reporting"}
    assert report["retention"] == "no shared history-key found"
    assert list(tmp_path.rglob("*")) == before
    assert all(item["evidence"] for item in report["suggestions"])


def test_local_composite_and_reusable_workflow_are_followed_once(tmp_path):
    write(tmp_path, ".github/workflows/tests.yml", """
jobs:
  local:
    steps:
      - uses: ./.github/actions/shared
  external:
    uses: other/project/.github/workflows/tests.yml@v1
  report:
    uses: gigaverse-app/ci-esta/.github/workflows/report.yml@v1
""")
    write(tmp_path, ".github/actions/shared/action.yml", """
runs:
  using: composite
  steps:
    - uses: ./.github/actions/shared
    - uses: gigaverse-app/pytest-selective/actions/test-impact@v1
    - uses: gigaverse-app/ci-esta/actions/restore-test-timings@v1
      with:
        history-key: lane-v1
    - uses: gigaverse-app/ci-esta/actions/learn-test-timings@v1
      with:
        history-key: lane-v1
""")
    report = audit(tmp_path)
    assert report["retention"] == "configured; verify lane keys and trusted writers"
    assert "timing-feedback" not in {item["id"] for item in report["suggestions"]}
    assert any("other/project" in item for item in report["limitations"])
    assert len(report["files"]) == 2


def test_incomplete_history_pair_is_actionable_and_ignore_only_suppresses_advice(tmp_path):
    write(tmp_path, ".github/workflows/tests.yml", """
jobs:
  tests:
    steps:
      - uses: gigaverse-app/ci-esta/actions/learn-test-timings@v1
        with:
          history-key: lane-v1
""")
    report = audit(tmp_path)
    assert "history-restore" in {item["id"] for item in report["suggestions"]}
    ignored = audit(tmp_path, "--ignore", "history-restore")
    assert "history-restore" not in {item["id"] for item in ignored["suggestions"]}
    assert ignored["actions"] == report["actions"]


def test_invalid_yaml_and_missing_local_action_are_reported_as_unknown(tmp_path):
    write(tmp_path, ".github/workflows/invalid.yml", "jobs: [broken")
    write(tmp_path, ".github/workflows/local.yml", "jobs: {test: {steps: [{uses: './missing'}]}}")
    report = audit(tmp_path)
    assert len(report["limitations"]) >= 2
    assert report["files"]


def test_bun_consumer_is_not_told_to_adopt_python_selection(tmp_path):
    write(tmp_path, ".github/workflows/test.yml", "jobs: {test: {steps: [{run: 'bun test'}]}}")
    report = audit(tmp_path)
    assert "python-selection" not in {item["id"] for item in report["suggestions"]}
    assert "bun-reporting" in {item["id"] for item in report["suggestions"]}


def test_inventory_does_not_publish_arbitrary_action_inputs(tmp_path):
    write(tmp_path, ".github/workflows/test.yml", """
jobs:
  test:
    steps:
      - uses: gigaverse-app/ci-esta/actions/restore-test-timings@v1
        with:
          history-key: lane-v1
          token: fake-secret-that-must-not-be-published
""")
    report = audit(tmp_path)
    assert "fake-secret" not in json.dumps(report)
    assert report["actions"][0]["inputs"]["history-key"] == "lane-v1"


def test_bun_copied_checkpoint_policy_is_discoverable(tmp_path):
    write(tmp_path, ".github/workflows/test.yml", """
jobs:
  test:
    steps:
      - uses: gigaverse-app/ci-esta/actions/run-bun-tests@v1
        with:
          full: "${{ github.run_attempt > 1 }}"
""")
    report = audit(tmp_path)
    assert "checkpoint-policy" in {item["id"] for item in report["suggestions"]}
    assert "python-selection" not in {item["id"] for item in report["suggestions"]}


SHA = "3d3c42e5aac5ba805825da76410c181273ba90b1"
TOX_CI = f"""
name: CI
on:
  pull_request:
  push:
    branches: [main]
jobs:
  build:
    name: Build
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@{SHA} # v7.0.1
  tests:
    name: Tests on ${{{{ matrix.python-version }}}}
    needs: build
    strategy:
      matrix:
        python-version: ${{{{ fromJson(needs.build.outputs.versions) }}}}
    steps:
      - uses: actions/setup-python@{SHA} # v7.1.0
      - run: uvx --with tox-uv tox run -f py-tests
  coverage:
    needs: tests
    if: always()
    steps:
      - run: coverage report --fail-under=100
  lint:
    needs: build
    strategy:
      matrix:
        os: [ubuntu-latest, windows-latest]
        tool: [ruff, mypy]
        exclude:
          - {{os: windows-latest, tool: mypy}}
    steps:
      - run: nox -s lint
  required:
    name: All required checks
    if: always()
    needs: [coverage, lint]
    steps:
      - uses: re-actors/alls-green@{SHA} # v1.3.0
        with:
          jobs: ${{{{ toJSON(needs) }}}}
  colors:
    needs: build
    steps:
      - run: tox run -f color
"""


def test_report_names_the_gate_its_blind_spots_and_the_measurement_to_run(tmp_path):
    write(tmp_path, ".github/workflows/ci.yml", TOX_CI)
    write(tmp_path, ".github/workflows/docs.yml", "name: Docs\non: push\njobs: {docs: {steps: [{run: make html}]}}")
    write(tmp_path, "tox.ini", "[tox]\n")
    report = audit(tmp_path)
    ci = next(flow for flow in report["workflows"] if flow["source"] == ".github/workflows/ci.yml")
    assert ci["triggers"] == ["pull_request", "push"]
    jobs = {job["id"]: job for job in ci["jobs"]}
    assert [job_id for job_id, job in jobs.items() if job["gate_candidate"]] == ["required"]
    assert jobs["tests"]["matrix"] and jobs["tests"]["matrix_size"] is None
    assert jobs["lint"]["matrix_size"] == 3
    assert jobs["tests"]["test_commands"] == ["tox"] and jobs["lint"]["test_commands"] == ["nox"]
    assert ci["outside_gate"] == ["colors"]
    suggestions = {item["id"]: item for item in report["suggestions"]}
    # coverage runs after failures, so a failing test job reaches the gate only through a job that can still pass.
    assert "tests" in suggestions["gate-indirect"]["advice"]
    assert suggestions["matrix-setup"]["evidence"] == [".github/workflows/ci.yml"]
    assert suggestions["reporting"]["evidence"] == [".github/workflows/ci.yml"]
    assert report["pinning"].startswith("all 3 external references are commit SHAs")
    assert "uv.lock" not in report["project_files"] and "tox.ini" in report["project_files"]
    measure = report["next_steps"][-1]
    assert "--workflow ci.yml" in measure and "--gate 'All required checks'" in measure


def test_gate_that_needs_its_test_jobs_directly_has_no_blind_spot(tmp_path):
    write(tmp_path, ".github/workflows/ci.yml", TOX_CI.replace("needs: [coverage, lint]", "needs: [tests, coverage, lint]"))
    report = audit(tmp_path)
    assert "gate-indirect" not in {item["id"] for item in report["suggestions"]}


def test_text_output_lists_each_workflow_and_next_step(tmp_path):
    write(tmp_path, ".github/workflows/ci.yml", TOX_CI)
    result = subprocess.run([sys.executable, "-m", "ci_esta.cli", "adoption", "--root", str(tmp_path)],
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert ".github/workflows/ci.yml (CI; pull_request, push): 6 jobs; aggregate gate: 'All required checks'" in result.stdout
    assert "not behind the gate: colors" in result.stdout
    assert "ci-esta report --repository OWNER/REPO" in result.stdout
