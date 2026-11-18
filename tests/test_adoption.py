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
    rendered = subprocess.run([sys.executable, "-m", "ci_esta.cli", "adoption", "--root", str(tmp_path)],
                              capture_output=True, text=True, check=True).stdout
    # The text readers see first says what a history-key is and that only timing-balanced shards need one.
    assert "timing retention: no shared history-key found (a history-key keeps learned test timings" in rendered
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
    assert "merged-pr-timing-promotion" in {item["id"] for item in report["suggestions"]}
    ignored = audit(tmp_path, "--ignore", "history-restore")
    assert "history-restore" not in {item["id"] for item in ignored["suggestions"]}
    assert ignored["actions"] == report["actions"]


def test_collector_is_a_shared_writer_and_satisfies_default_promotion_advice(tmp_path):
    write(tmp_path, ".github/workflows/history.yml", """
jobs:
  timings:
    steps:
      - uses: gigaverse-app/ci-esta/actions/restore-test-timings@v1
        with:
          history-key: unit
      - uses: gigaverse-app/ci-esta/actions/promote-merged-pr-timings@v1
        with:
          history-key: unit
""")
    report = audit(tmp_path)
    assert report["retention"] == "configured; verify lane keys and trusted writers"
    assert not {"history-writer", "merged-pr-timing-promotion"}.intersection(
        item["id"] for item in report["suggestions"])


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
    # A reusable workflow names the step after the receipt its caller passes as an input.
    passed = RECEIPT.replace("needs.plan.outputs.receipt", "inputs.validation-receipt")
    assert "reuse-receipt" not in reuse_suggestions(tmp_path, MARKER, passed)


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


def test_existing_timing_pair_does_not_need_an_additional_collector(tmp_path):
    write(tmp_path, ".github/workflows/tests.yml", """
jobs:
  timings:
    steps:
      - uses: gigaverse-app/ci-esta/actions/restore-test-timings@v1
        with:
          history-key: unit
      - uses: gigaverse-app/ci-esta/actions/learn-test-timings@v1
        with:
          history-key: unit
          complete-files: 'true'
""")
    report = audit(tmp_path)
    assert not {"history-writer", "history-restore", "merged-pr-timing-promotion"}.intersection(
        item["id"] for item in report["suggestions"])


def test_bun_action_execution_and_history_are_visible_to_adopters(tmp_path):
    write(tmp_path, '.github/workflows/test.yml', '''
name: Native tests
jobs:
  unit:
    steps:
      - uses: gigaverse-app/ci-esta/actions/run-bun-tests@v1
        with:
          timing-history: ${{ runner.temp }}/bun-history/unit.json
  gate:
    needs: unit
    steps:
      - uses: gigaverse-app/ci-esta/actions/validation-gate@v1
''')
    report = audit(tmp_path)
    assert report['workflows'][0]['jobs'][0]['test_commands'] == ['bun test']
    assert any('--workflow test.yml' in step for step in report['next_steps'])
    assert 'Bun timing-history configured' in report['retention']
    assert 'verify persistence' in report['retention']
    assert 'python-selection' not in {item['id'] for item in report['suggestions']}


def test_bun_report_action_does_not_claim_test_execution(tmp_path):
    write(tmp_path, '.github/workflows/report.yml', '''
jobs:
  report:
    steps:
      - uses: gigaverse-app/ci-esta/actions/report-bun-tests@v1
''')
    report = audit(tmp_path)
    assert report['workflows'][0]['jobs'][0]['test_commands'] == []
    assert report['retention'] == 'no shared history-key found'


DEVICE_CHAIN = """
name: Device measurement
on: [workflow_dispatch]
jobs:
  prepare: {steps: [{run: echo plan}]}
  baseline-1: {needs: prepare, uses: ./.github/workflows/measure.yml}
  baseline-2: {needs: [prepare, baseline-1], if: always(), uses: ./.github/workflows/measure.yml}
  baseline-report:
    needs: [prepare, baseline-1, baseline-2]
    if: always()
    steps:
      - run: test "${{ needs.baseline-1.result }}" = success
  load:
    needs: [prepare, baseline-report]
    if: always()
    uses: ./.github/workflows/measure.yml
  verdict:
    needs: [prepare, load]
    if: always()
    steps:
      - uses: actions/download-artifact@v4
      - run: node publish-verdicts.js
"""


def test_ordered_reusable_work_and_artifact_verdicts_are_not_told_to_widen_needs(tmp_path):
    # Sequential device measurements use always() to keep one device busy in turn; they do work, not aggregate.
    write(tmp_path, ".github/workflows/device.yml", DEVICE_CHAIN)
    write(tmp_path, ".github/workflows/measure.yml", "on: workflow_call\njobs: {run: {steps: [{run: measure}]}}")
    report = audit(tmp_path)
    jobs = {job["id"]: job for job in next(f for f in report["workflows"] if f["source"].endswith("device.yml"))["jobs"]}
    assert not jobs["load"]["gate_candidate"] and not jobs["baseline-2"]["gate_candidate"]
    assert jobs["baseline-report"]["judges_results"] and not jobs["verdict"]["judges_results"]
    # The verdict reads artifacts, so adding jobs to its `needs` would not change what it reports.
    assert "gate-indirect" not in {item["id"] for item in report["suggestions"]}


def test_a_step_env_reading_results_makes_a_gate_that_needs_direct_prerequisites(tmp_path):
    workflow = DEVICE_CHAIN.replace(
        "      - run: node publish-verdicts.js",
        "      - run: node publish-verdicts.js\n        env:\n          RESULTS: ${{ needs.load.result }}")
    write(tmp_path, ".github/workflows/device.yml", workflow)
    write(tmp_path, ".github/workflows/measure.yml", "on: workflow_call\njobs: {run: {steps: [{run: measure}]}}")
    advice = {item["id"]: item["advice"] for item in audit(tmp_path)["suggestions"]}
    assert "gate 'verdict' reaches baseline-report only through 'load'" in advice["gate-indirect"]


def test_test_lanes_and_admission_conditions_are_work_not_gates(tmp_path):
    workflow = """
name: CI
on: [push]
jobs:
  base: {steps: [{run: echo base}]}
  plan: {steps: [{run: echo plan}]}
  unit:
    needs: [base, plan]
    if: ${{ !cancelled() && needs.base.result == 'success' }}
    steps: [{run: bun test}]
  gate:
    needs: [base, plan, unit]
    if: always()
    steps:
      - run: test "${{ needs.unit.result }}" = success
"""
    write(tmp_path, ".github/workflows/ci.yml", workflow)
    jobs = {job["id"]: job for job in audit(tmp_path)["workflows"][0]["jobs"]}
    assert [job_id for job_id, job in jobs.items() if job["gate_candidate"]] == ["gate"]
    assert not jobs["unit"]["judges_results"]


REVIEWED = """reviewed:
  - suggestion: gate-indirect
    evidence: .github/workflows/device.yml
    match: "gate 'verdict'"
    reason: The verdict reports the load measurement only; baselines are graded separately by design.
  - suggestion: matrix-setup
    evidence: .github/workflows/gone.yml
    reason: Removed workflow.
"""


def test_reviewed_decisions_move_findings_out_of_open_suggestions_and_flag_stale_ones(tmp_path):
    workflow = DEVICE_CHAIN.replace(
        "      - run: node publish-verdicts.js",
        "      - run: node publish-verdicts.js\n        env:\n          RESULTS: ${{ needs.load.result }}")
    write(tmp_path, ".github/workflows/device.yml", workflow)
    write(tmp_path, ".github/workflows/measure.yml", "on: workflow_call\njobs: {run: {steps: [{run: measure}]}}")
    write(tmp_path, ".github/ci-esta-reviewed.yaml", REVIEWED)
    report = audit(tmp_path)
    assert "gate-indirect" not in {item["id"] for item in report["suggestions"]}
    assert [entry["suggestion"]["id"] for entry in report["reviewed"]] == ["gate-indirect"]
    assert report["reviewed"][0]["reason"].startswith("The verdict reports")
    assert [entry["evidence"] for entry in report["stale_reviews"]] == [".github/workflows/gone.yml"]
    text = subprocess.run([sys.executable, "-m", "ci_esta.cli", "adoption", "--root", str(tmp_path)],
                          capture_output=True, text=True).stdout
    assert "Reviewed in .github/ci-esta-reviewed.yaml (1):" in text and "Stale entries" in text


@pytest.mark.parametrize("content", [
    "reviewed:\n  - suggestion: gate-indirect\n    evidence: x.yml\n",  # no reason
    "reviewed:\n  - suggestion: gate-indirect\n    evidence: x.yml\n    reason: ''\n",
    "reviewed:\n  - suggestion: gate-indirect\n    evidence: x.yml\n    reason: r\n    because: typo\n",
    "reviewed: []\n",
])
def test_a_decision_without_a_reason_or_with_unknown_keys_fails_loudly(tmp_path, content):
    write(tmp_path, ".github/ci-esta-reviewed.yaml", content)
    result = subprocess.run([sys.executable, "-m", "ci_esta.cli", "adoption", "--root", str(tmp_path)],
                            capture_output=True, text=True)
    assert result.returncode == 2 and "ci-esta-reviewed.yaml" in result.stderr
