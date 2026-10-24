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
