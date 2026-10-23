"""Replay the real GitHub client and history adapter across remote boundaries."""

import io
import json
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest

from ci_esta.ci_observability.github import GitHubActionsClient
from ci_esta.testing import timing_artifacts, timing_feedback
from ci_esta.testing.timing_history import Observation
from ci_esta.testing.timing_store import TimingHistory, combine_histories, observation_stamp

NOW = datetime(2026, 10, 24, tzinfo=timezone.utc)


def checkpoint(run_id, file, seconds, *, day=23, covered=()):
    stamp = observation_stamp(NOW.replace(day=day), run_id, 1)
    return TimingHistory(
        key="unit", observations={file: Observation(seconds, stamp)},
        inventory_stamp=stamp, inventory_at=NOW.replace(day=day),
        tracked_files={"test_a.py", "test_b.py"},
        producer_run_id=run_id, producer_attempt=1, covered_artifact_ids=set(covered),
    )


class ArtifactServer:
    """HTTP-boundary fake: immutable archives, run provenance and request recording."""

    def __init__(self, states):
        self.states = states
        self.downloads = []
        self.runs = {
            state.producer_run_id: dict(
                id=state.producer_run_id, name="Tests", run_attempt=1, event="push", status="completed",
                conclusion="success", head_branch="main", head_sha="a" * 40,
                created_at="2026-10-23T00:00:00Z", run_started_at="2026-10-23T00:00:00Z",
            ) for state in states.values()
        }
        self.forks = set()

    def handle(self, request):
        path = request.url.path
        if path.endswith("/actions/artifacts"):
            assert request.url.params["name"] == timing_artifacts.artifact_name("unit")
            return httpx.Response(200, json={"artifacts": [
                dict(id=id, name=timing_artifacts.artifact_name("unit"), expired=False,
                     created_at=f"2026-10-23T00:00:{index:02d}Z",
                     workflow_run=dict(id=state.producer_run_id, repository_id=1,
                                       head_repository_id=2 if id in self.forks else 1))
                for index, (id, state) in enumerate(self.states.items())
            ]})
        if "/actions/runs/" in path:
            return httpx.Response(200, json=self.runs[int(path.split("/")[-1])])
        if path.endswith("/zip"):
            id = int(path.split("/")[-2])
            self.downloads.append(id)
            content = io.BytesIO()
            with zipfile.ZipFile(content, "w") as archive:
                archive.writestr("history.json", self.states[id].model_dump_json())
            return httpx.Response(200, content=content.getvalue())
        raise AssertionError(path)

    def client(self):
        return GitHubActionsClient("org/repo", "fake", transport=httpx.MockTransport(self.handle))


def test_concurrent_artifact_updates_and_checkpoint_compaction():
    server = ArtifactServer({10: checkpoint(1, "test_a.py", 10), 20: checkpoint(2, "test_b.py", 20)})
    client = server.client()
    state = combine_histories(timing_artifacts.read_histories(client, "unit", "main"), "unit", NOW)
    assert {key: value.seconds for key, value in state.observations.items()} == {"test_a.py": 10, "test_b.py": 20}
    assert set(server.downloads) == {10, 20}
    assert state.covered_artifact_ids == {10, 20}
    # Next publication compacts both ancestors. Reader fetches one checkpoint.
    state.producer_run_id = 3
    server.states[30] = state
    server.runs[3] = {**server.runs[1], "id": 3}
    server.downloads.clear()
    combined = combine_histories(timing_artifacts.read_histories(client, "unit", "main"), "unit", NOW)
    assert combined.observations == state.observations
    assert server.downloads == [30]
    client.close()


def test_late_publication_cannot_replace_newer_observation():
    server = ArtifactServer({10: checkpoint(1, "test_a.py", 10), 20: checkpoint(2, "test_a.py", 99, day=20)})
    client = server.client()
    state = combine_histories(timing_artifacts.read_histories(client, "unit", "main"), "unit", NOW)
    assert state.observations["test_a.py"].seconds == 10
    client.close()


@pytest.mark.parametrize("change", ["fork", "pr", "branch", "failed", "pending", "attempt"])
def test_only_current_successful_trusted_branch_producers_are_consumed(change):
    server = ArtifactServer({10: checkpoint(1, "test_a.py", 10)})
    if change == "fork":
        server.forks.add(10)
    elif change == "pr":
        server.runs[1]["event"] = "pull_request"
    elif change == "branch":
        server.runs[1]["head_branch"] = "feature"
    elif change == "failed":
        server.runs[1]["conclusion"] = "failure"
    elif change == "pending":
        server.runs[1]["status"] = "in_progress"
    else:
        server.runs[1]["run_attempt"] = 2
    client = server.client()
    assert timing_artifacts.read_histories(client, "unit", "main") == []
    client.close()


def test_download_budget_never_silently_discards_an_uncovered_writer():
    server = ArtifactServer({10: checkpoint(1, "test_a.py", 10), 20: checkpoint(2, "test_b.py", 20)})
    client = server.client()
    with pytest.raises(ValueError, match="budget"):
        timing_artifacts.read_histories(client, "unit", "main", max_downloads=1)
    client.close()


@pytest.mark.parametrize("event,branch,publish", [("push", "main", True), ("pull_request", "main", False),
                                                ("push", "feature", False)])
def test_action_learns_partial_run_and_gates_publication(tmp_path, monkeypatch, event, branch, publish):
    monkeypatch.chdir(tmp_path)
    import subprocess
    subprocess.run(["git", "init", "-q"], check=True)
    Path("test_a.py").write_text("def test_ok(): pass\n")
    Path("test_b.py").write_text("def test_ok(): pass\n")
    subprocess.run(["git", "add", "*.py"], check=True)
    Path("junit.xml").write_text('<testsuite><testcase file="test_b.py" time="20"/></testsuite>')
    server = ArtifactServer({10: checkpoint(1, "test_a.py", 10)})
    server.runs[2] = {**server.runs[1], "id": 2, "event": event, "head_branch": branch, "status": "in_progress"}
    monkeypatch.setattr(timing_feedback, "github_client", server.client)
    for key, value in {
        "INPUT_JUNIT_PATTERN": "junit.xml", "INPUT_TIMING_OUTPUT": "costs.json",
        "INPUT_HISTORY_KEY": "unit", "INPUT_COMPLETE_FILES": "true", "INPUT_HISTORY_BRANCH": "main",
        "GITHUB_RUN_ID": "2", "GITHUB_REF": f"refs/heads/{branch}", "GITHUB_OUTPUT": "output",
        "RUNNER_TEMP": str(tmp_path),
    }.items():
        monkeypatch.setenv(key, value)
    timing_feedback.main()
    assert json.loads(Path("costs.json").read_text()) == {"test_a.py": 10, "test_b.py": 20}
    assert f"publish={str(publish).lower()}" in Path("output").read_text()


def test_restore_keeps_unobserved_seed_and_replaces_observed_nodes(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    Path("costs.json").write_text(json.dumps({"test_a.py::old": 99, "test_b.py::seed": 20}))
    server = ArtifactServer({10: checkpoint(1, "test_a.py", 10)})
    monkeypatch.setattr(timing_artifacts, "github_client", server.client)
    for key, value in {"INPUT_TIMING_OUTPUT": "costs.json", "INPUT_HISTORY_KEY": "unit",
                       "INPUT_HISTORY_BRANCH": "main"}.items():
        monkeypatch.setenv(key, value)
    timing_artifacts.restore()
    assert json.loads(Path("costs.json").read_text()) == {"test_a.py": 10, "test_b.py": 20}


@pytest.mark.parametrize("seed", [True, False])
def test_unavailable_history_preserves_seed_or_unknown_cost_fallback(tmp_path, monkeypatch, seed):
    monkeypatch.chdir(tmp_path)
    if seed:
        Path("costs.json").write_text('{"test_a.py":42}')
    monkeypatch.setattr(timing_artifacts, "github_client", lambda: GitHubActionsClient(
        "org/repo", "fake", transport=httpx.MockTransport(lambda request: httpx.Response(403)),
    ))
    for key, value in {"INPUT_TIMING_OUTPUT": "costs.json", "INPUT_HISTORY_KEY": "unit",
                       "INPUT_HISTORY_BRANCH": "main"}.items():
        monkeypatch.setenv(key, value)
    timing_artifacts.restore()
    assert json.loads(Path("costs.json").read_text()) == ({"test_a.py": 42} if seed else {})
