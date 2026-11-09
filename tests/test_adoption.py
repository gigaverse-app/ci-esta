"""Adoption advice reads actual workflow wiring without executing consumer code."""

import json
import subprocess
import sys
from pathlib import Path

import pytest


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


@pytest.mark.parametrize("matrix", [
    {"os": ["linux", "windows"], "exclude": [{"os": "macos"}]},
    {"os": ["linux", "windows"], "include": [{"os": "linux", "extra": True}]},
])
def test_adoption_counts_expanded_matrix_jobs_not_include_exclude_entries(tmp_path, matrix):
    write(tmp_path, ".github/workflows/ci.yml", json.dumps({
        "jobs": {"tests": {"strategy": {"matrix": matrix}, "steps": [{"run": "pytest"}]}},
    }))
    assert audit(tmp_path)["workflows"][0]["jobs"][0]["matrix_size"] == 2


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


PACKED = """
name: Tests
on: [pull_request]
jobs:
  plan:
    outputs:
      pools: ${{ steps.pools.outputs.pools }}
    steps:
      - id: pools
        uses: gigaverse-app/ci-esta/actions/plan-runner-pools@v1
        with: {shards: '4', shards-per-runner: '2'}
  tests-linux:
    name: ${{ join(matrix.pool.versions, ', ') }}
    needs: %s
    strategy:
      matrix:
        pool: ${{ fromJSON(needs.%s.outputs.pools) }}
    steps:
      - run: uv run --locked tox run-parallel -e "$ENVS"
"""


def test_matrix_already_packed_by_plan_runner_pools_is_not_told_to_pack(tmp_path):
    write(tmp_path, ".github/workflows/tests.yaml", PACKED % ("plan", "plan"))
    report = audit(tmp_path)
    job = next(job for job in report["workflows"][0]["jobs"] if job["id"] == "tests-linux")
    assert job["packed_by"] == "plan"
    assert "matrix-setup" not in {item["id"] for item in report["suggestions"]}
    text = subprocess.run([sys.executable, "-m", "ci_esta.cli", "adoption", "--root", str(tmp_path)],
                          capture_output=True, text=True).stdout
    assert "tests-linux: run-time matrix; packed by 'plan'; runs tox" in text


def test_matrix_from_an_unrelated_job_output_is_still_a_packing_candidate(tmp_path):
    workflow = (PACKED % ("[plan, versions]", "versions")).replace("jobs:\n", "jobs:\n  versions: {}\n", 1)
    write(tmp_path, ".github/workflows/tests.yaml", workflow)
    report = audit(tmp_path)
    assert "matrix-setup" in {item["id"] for item in report["suggestions"]}


def test_sha_pinned_actions_keep_the_v1_default_unless_zizmor_rejects_tags(tmp_path):
    write(tmp_path, ".github/workflows/ci.yml", TOX_CI)
    assert "use `@v1` for CI-esta actions unless" in audit(tmp_path)["pinning"]
    write(tmp_path, ".pre-commit-config.yaml", "repos:\n  - repo: https://github.com/zizmorcore/zizmor-pre-commit\n")
    pinning = audit(tmp_path)["pinning"]
    assert ".pre-commit-config.yaml runs zizmor" in pinning and "@<sha> # vX.Y.Z" in pinning


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


REUSE_PLANNER = """
jobs:
  plan:
    outputs:
      receipt: ${{ steps.evidence.outputs.receipt }}
    steps:
%s
      - id: evidence
        uses: gigaverse-app/ci-esta/actions/resolve-lane-evidence@v1
        with:
          lanes: '{"tests":"Tests"}'
          input-paths: '["src","tests"]'
          reuse-after-merge: 'true'
  tests:
    name: Tests
    needs: plan
    steps:
      - run: pytest -q
%s
"""
MARKER = """      - name: "PR evidence #${{ github.event.pull_request.number }} head ${{ github.event.pull_request.head.sha }}"
        if: github.event_name == 'pull_request'
        run: 'true'"""
RECEIPT = """      - name: ${{ needs.plan.outputs.receipt || 'No execution receipt' }}
        if: ${{ needs.plan.outputs.receipt != '' }}
        run: 'true'"""


def reuse_suggestions(tmp_path: Path, marker: str, receipt: str) -> set[str]:
    write(tmp_path, ".github/workflows/ci.yml", REUSE_PLANNER % (marker, receipt))
    return {item["id"] for item in audit(tmp_path)["suggestions"]}


def test_reuse_after_merge_without_ownership_marker_is_flagged(tmp_path):
    # pytest-quint-connect #34: every PR run lacked pull_requests metadata, so the push after each merge
    # rejected them as "not associated with PR" and reran all lanes until the marker was added (#37).
    assert "reuse-ownership-marker" in reuse_suggestions(tmp_path, "", RECEIPT)
    assert "reuse-ownership-marker" not in reuse_suggestions(tmp_path, MARKER, RECEIPT)


def test_marker_inside_a_composite_action_does_not_count(tmp_path):
    write(tmp_path, ".github/actions/mark/action.yml", "runs:\n  using: composite\n  steps:\n" + MARKER.replace("      -", "    -"))
    write(tmp_path, ".github/workflows/ci.yml", REUSE_PLANNER % ("      - uses: ./.github/actions/mark", RECEIPT))
    assert "reuse-ownership-marker" in {item["id"] for item in audit(tmp_path)["suggestions"]}


def test_lane_evidence_without_a_receipt_step_is_flagged(tmp_path):
    assert "reuse-receipt" in reuse_suggestions(tmp_path, MARKER, "")
    assert "reuse-receipt" not in reuse_suggestions(tmp_path, MARKER, RECEIPT)
    # A receipt published under another output name, like pytest-selective's contract-receipt, still counts.
    named = RECEIPT.replace("outputs.receipt", "outputs.contract-receipt")
    assert "reuse-receipt" not in reuse_suggestions(tmp_path, MARKER, named)


def test_reuse_without_merge_reuse_needs_no_marker(tmp_path):
    write(tmp_path, ".github/workflows/ci.yml", (REUSE_PLANNER % ("", RECEIPT)).replace("reuse-after-merge: 'true'", "reuse-after-merge: 'false'"))
    assert "reuse-ownership-marker" not in {item["id"] for item in audit(tmp_path)["suggestions"]}


RELEASE_PLEASE = """
on:
%s
jobs:
  release-please:
    steps:
      - uses: googleapis/release-please-action@v4
"""
ON_PUSH = "  push:\n    branches: [main]"
AFTER_CI = "  workflow_run:\n    workflows: [CI]\n    branches: [main]\n    types: [completed]"


def release_suggestions(tmp_path: Path, trigger: str, version_only: bool = True) -> set[str]:
    planner = REUSE_PLANNER % (MARKER, RECEIPT)
    if version_only:
        planner = planner.replace("reuse-after-merge: 'true'", "reuse-after-merge: 'true'\n          reuse-version-only-release: 'true'")
    write(tmp_path, ".github/workflows/ci.yml", planner)
    write(tmp_path, ".github/workflows/release-please.yml", RELEASE_PLEASE % trigger)
    return {item["id"] for item in audit(tmp_path)["suggestions"]}


def test_version_only_reuse_with_release_please_on_push_is_flagged(tmp_path):
    # pytest-quint-connect #36 refreshed the release PR on every push to main. Its CI then raced main's CI on the
    # same code, found no receipt, and the 1.2.1 release PR reran all seven test jobs that main proved minutes later.
    assert "release-refresh-timing" in release_suggestions(tmp_path, ON_PUSH)


def test_release_please_after_main_ci_needs_nothing(tmp_path):
    assert "release-refresh-timing" not in release_suggestions(tmp_path, AFTER_CI)


def test_release_please_on_push_without_version_only_reuse_is_fine(tmp_path):
    assert "release-refresh-timing" not in release_suggestions(tmp_path, ON_PUSH, version_only=False)
