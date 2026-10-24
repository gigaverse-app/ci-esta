"""Real stdlib producer -> uploaded JSON contract -> report, including PR merge/head separation."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from ci_esta.ci_observability.efficiency import MEASUREMENT, collect_measurements
from ci_esta.ci_observability.github import GitHubActionsClient
from ci_esta.ci_observability.models import GitHubRunV1
from ci_esta.ci_observability.report import render_markdown
from tests.ci_observability.builders import RECORDED_AT, artifact
from tests.ci_observability.efficiency_builders import report


@pytest.mark.parametrize("enabled,hit,usable,restore,expected", [
    ("true", "true", "true", "success", "hit"),
    ("true", "true", "false", "success", "repaired"),
    ("true", "false", "false", "success", "miss"),
    ("false", "", "false", "skipped", "disabled"),
    ("true", "", "false", "failure", "unavailable"),
])
def test_cache_producer_and_report_use_verified_artifact_outcomes(tmp_path, enabled, hit, usable, restore, expected):
    event = tmp_path / "event.json"
    event.write_text(json.dumps({"pull_request": {"head": {"sha": "a" * 40}}}))
    output = tmp_path / "outputs"
    subprocess.run([sys.executable, "scripts/ci/record_measurement.py", "cache"], check=True, env={
        **os.environ, "GITHUB_EVENT_PATH": str(event), "GITHUB_SHA": "b" * 40,
        "GITHUB_RUN_ID": "431", "GITHUB_RUN_ATTEMPT": "2", "GITHUB_JOB": "tests",
        "RUNNER_TEMP": str(tmp_path), "GITHUB_OUTPUT": str(output), "MEASUREMENT_SCOPE": ".:key",
        "CACHE_ENABLED": enabled, "CACHE_HIT": hit, "CACHE_USABLE": usable,
        "CACHE_RESTORE_OUTCOME": restore, "CACHE_SYNC_SECONDS": "1.25",
    })
    outputs = dict(line.split("=", 1) for line in output.read_text().splitlines())
    payload = Path(outputs["measurement-path"]).read_bytes()
    measured = MEASUREMENT.validate_json(payload)
    assert (measured.head_sha, measured.outcome, measured.sync_seconds) == ("a" * 40, expected, 1.25)
    upload = artifact(1, 431).model_copy(update={"name": outputs["measurement-name"]})

    class API(GitHubActionsClient):
        def __init__(self):
            pass

        def list_artifacts(self, name, run_id):
            assert name is None and run_id == 431
            return [upload]

        def read_single_file_artifact(self, artifact_id):
            assert artifact_id == 1
            return payload

    run = GitHubRunV1(id=431, name="CI", run_attempt=2, head_sha="a" * 40,
                     status="completed", created_at=RECORDED_AT)
    records, errors = collect_measurements(API(), run, [])
    assert records == [measured] and errors == []
    sticky = render_markdown(report().model_copy(update={"measurements": records}))
    assert f"| `tests` | {expected} |" in sticky
    if expected in {"hit", "miss", "repaired"}:
        assert f"{int(expected == 'hit')}/1</strong> environment cache hits" in sticky
    else:
        label = "disabled" if expected == "disabled" else "unmeasured"
        assert f"1 {label}</strong> environment caches" in sticky
    assert "Cache time saved is unavailable" in sticky


@pytest.mark.parametrize("restore,hit,matched,expected", [
    ("success", "true", "primary", "exact-hit"),
    ("success", "false", "older", "fallback-hit"),
    ("success", "", "", "miss"),
    ("success", "false", "", "unavailable"),
    ("failure", "true", "primary", "unavailable"),
    ("skipped", "", "", "skipped"),
])
def test_download_cache_outcomes_require_restore_evidence(tmp_path, restore, hit, matched, expected):
    event = tmp_path / "event.json"
    event.write_text(json.dumps({"pull_request": {"head": {"sha": "a" * 40}}}))
    output = tmp_path / "outputs"
    subprocess.run([sys.executable, "scripts/ci/record_measurement.py", "cache-operation"], check=True, env={
        **os.environ, "GITHUB_EVENT_PATH": str(event), "GITHUB_SHA": "b" * 40,
        "GITHUB_RUN_ID": "431", "GITHUB_RUN_ATTEMPT": "2", "GITHUB_JOB": "Tests",
        "RUNNER_TEMP": str(tmp_path), "GITHUB_OUTPUT": str(output), "MEASUREMENT_SCOPE": "Bun dependencies",
        "CACHE_KIND": "download", "CACHE_RESTORE_OUTCOME": restore, "CACHE_HIT": hit,
        "CACHE_MATCHED_KEY": matched, "CACHE_PRIMARY_KEY": "primary", "CACHE_RESTORE_SECONDS": "1.25",
        "CACHE_SAVE_SECONDS": "", "CACHE_SYNC_SECONDS": "2.5", "CACHE_SYNC_OUTCOME": "success",
    })
    outputs = dict(line.split("=", 1) for line in output.read_text().splitlines())
    measured = MEASUREMENT.validate_json(Path(outputs["measurement-path"]).read_bytes())
    assert measured.head_sha == "a" * 40
    assert measured.outcome == expected
    sticky = render_markdown(report().model_copy(update={"measurements": [measured]}))
    assert f"| `Tests` | `Bun dependencies` | download | {expected} |" in sticky
    assert "unavailable" in sticky
    assert "Every recorded environment passed locked synchronization" not in sticky
    assert "Cache time saved is unavailable" in sticky
