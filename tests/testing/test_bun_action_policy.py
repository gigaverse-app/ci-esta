"""The Bun action forwards its actual event and override to the shared Python policy."""

import argparse
import json

import pytest

from ci_esta.testing.bun.cli import request_from_env


@pytest.mark.parametrize("attempt", ["1", "2"])
@pytest.mark.parametrize("event,labels,full", [
    ("pull_request", [], False),
    ("pull_request", [{"name": "test:full"}], True),
    ("pull_request", [{"name": "unrelated"}], False),
    ("pull_request", None, True),
    ("push", [], False), ("workflow_dispatch", [], True),
    ("workflow_call", [], True), ("schedule", [], True), ("release", [], True), ("", [], True),
])
def test_action_uses_event_policy_without_turning_reruns_into_full_work(tmp_path, monkeypatch, event, labels, full, attempt):
    event_path = tmp_path / "event.json"
    event_path.write_text(json.dumps({"pull_request": {"labels": labels}}))
    monkeypatch.setenv("GITHUB_EVENT_NAME", event)
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(event_path))
    monkeypatch.setenv("GITHUB_RUN_ATTEMPT", attempt)
    monkeypatch.setenv("BUN_TEST_INVENTORY", "inventory.json")
    monkeypatch.setenv("BUN_TEST_OUTPUT", str(tmp_path))
    monkeypatch.setenv("BUN_TEST_FULL", "auto")
    assert request_from_env().full is full
    monkeypatch.setenv("BUN_TEST_FULL", "true" if not full else "false")
    assert request_from_env().full is not full


def test_invalid_override_is_not_silently_treated_as_selective(monkeypatch):
    monkeypatch.setenv("BUN_TEST_FULL", "typo")
    with pytest.raises(argparse.ArgumentTypeError, match="full must be"):
        request_from_env()
