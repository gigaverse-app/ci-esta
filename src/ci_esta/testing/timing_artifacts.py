"""GitHub adapter for retained timings. No mutable remote cache or writer lock."""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

import httpx

from ci_esta.ci_observability.github import GitHubActionsClient
from ci_esta.testing.timing_history import Observation
from ci_esta.testing.timing_store import TimingHistory, combine_histories


def artifact_name(key: str) -> str:
    return "ci-esta-history-v1-" + hashlib.sha256(key.encode()).hexdigest()[:32]


def read_histories(client: GitHubActionsClient, key: str, branch: str, max_downloads: int = 20) -> list[TimingHistory]:
    """Read every uncovered writer, skipping ancestors already in a checkpoint.

Concurrent writers have separate artifact IDs. A checkpoint can cover an ID
only after downloading it; readers therefore cannot skip an unseen update.
Exceeding the budget fails without publishing a truncated replacement.
    """
    if max_downloads < 1:
        raise ValueError("history-max-downloads must be positive")
    states: list[TimingHistory] = []
    covered: set[int] = set()
    downloads = 0
    for artifact in client.list_artifacts(artifact_name(key)):
        if artifact.id in covered or not artifact.from_same_repository or artifact.workflow_run is None:
            continue
        run = client.get_run(artifact.workflow_run.id)
        if run.head_branch != branch or run.event not in {"push", "schedule", "workflow_dispatch"}:
            continue
        if run.status != "completed" or run.conclusion != "success":
            continue
        if downloads >= max_downloads:
            raise ValueError("uncovered timing histories exceed history-max-downloads; increase the budget")
        state = TimingHistory.model_validate_json(client.read_single_file_artifact(artifact.id))
        downloads += 1
        if state.key != key:
            raise ValueError("timing artifact key mismatch")
        if (state.producer_run_id, state.producer_attempt) != (run.id, run.run_attempt):
            continue
        states.append(state)
        covered.update(state.covered_artifact_ids)
        covered.add(artifact.id)
    if states:
        states[-1].covered_artifact_ids.update(covered)
    return states


def history_branch() -> str:
    return os.environ.get("INPUT_HISTORY_BRANCH") or json.loads(
        Path(os.environ["GITHUB_EVENT_PATH"]).read_text()
    )["repository"]["default_branch"]


def github_client() -> GitHubActionsClient:
    return GitHubActionsClient(
        os.environ["GITHUB_REPOSITORY"], os.environ["GH_TOKEN"],
        api_url=os.environ.get("GITHUB_API_URL", "https://api.github.com"),
    )


def action_histories(client: GitHubActionsClient, key: str) -> list[TimingHistory]:
    return read_histories(client, key, history_branch(), int(os.environ.get("INPUT_HISTORY_MAX_DOWNLOADS", "20")))


def restore() -> None:
    """On unavailable history keep a seed, or create {} for inventory fallback."""
    output = Path(os.environ["INPUT_TIMING_OUTPUT"])
    key = os.environ["INPUT_HISTORY_KEY"]
    client = github_client()
    try:
        states = action_histories(client, key)
        state = combine_histories(states, key, datetime.now(timezone.utc))
        if output.exists() and states:
            # A committed seed remains useful for files never measured by this
            # history. Replace all nodes of observed files, never add their cost twice.
            seed = json.loads(output.read_text())
            measured = {node.split("::", 1)[0] for node in state.observations}
            for node, seconds in seed.items():
                if node.split("::", 1)[0] not in measured:
                    state.observations[node] = Observation(float(seconds), "seed")
            state = TimingHistory.model_validate(state.model_dump())
        if states or not output.exists():
            state.export(output)
        print(f"Restored {len(state.observations)} timing observations from {len(states)} checkpoints")
    except (ValueError, OSError, httpx.HTTPError) as exc:
        if os.environ.get("INPUT_HISTORY_STRICT", "false") == "true":
            raise
        print(f"::warning::Timing history unavailable ({type(exc).__name__}); retaining seed or inventory fallback")
        if not output.exists():
            TimingHistory(key=key).export(output)
    finally:
        client.close()


if __name__ == "__main__":
    restore()
