"""Node consumers retain the Python checkpoint contract without installing Python."""
import json
import subprocess
from pathlib import Path

import pytest
from pytest_selective.checkpoint import full_checkpoint_reason

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("value", ["auto", "true", "false"])
@pytest.mark.parametrize("attempt", ["1", "2"])
@pytest.mark.parametrize("event,payload", [
    ("pull_request", {"pull_request": {"labels": []}}),
    ("pull_request", {"pull_request": {"labels": [{"name": "test:full"}]}}),
    ("pull_request", {"pull_request": {"labels": [{"name": "unrelated"}]}}),
    ("pull_request", {"pull_request": {}}),
    ("pull_request", {"pull_request": {"labels": [None]}}),
    ("pull_request", None),
    ("push", {}), ("workflow_dispatch", {}), ("workflow_call", {}),
    ("schedule", {}), ("release", {}), ("unknown", {}), ("", {}),
])
def test_node_checkpoint_matches_installed_python_policy(tmp_path, monkeypatch, event, payload, attempt, value):
    event_path = tmp_path / "event.json"
    if payload is not None:
        event_path.write_text(json.dumps(payload))
    monkeypatch.setenv("GITHUB_EVENT_NAME", event)
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(event_path))
    monkeypatch.setenv("GITHUB_RUN_ATTEMPT", attempt)
    result = subprocess.run([
        "node", "--input-type=module", "-e",
        "import {fullCheckpointReason} from './actions/run-bun-tests/checkpoint.mjs';"
        "process.stdout.write(JSON.stringify(fullCheckpointReason(process.argv[1])));", value,
    ], cwd=ROOT, capture_output=True, text=True, check=True)
    assert json.loads(result.stdout) == full_checkpoint_reason(value)
