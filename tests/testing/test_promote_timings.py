import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest

from ci_esta.testing import promote_timings
from ci_esta.testing.timing_artifacts import read_histories
from ci_esta.testing.timing_store import TimingHistory, combine_histories
from tests.testing.git_repo import commit, write
from tests.testing.merged_pr_server import MergedPRServer
from tests.testing.test_timing_artifacts import ArtifactServer


class CollectionServer(MergedPRServer):
    def handle(self, request):
        if request.url.path.endswith("/actions/artifacts"):
            return httpx.Response(200, json={"artifacts": []})
        if "/commits/" in request.url.path and request.url.path.endswith("/pulls"):
            return httpx.Response(200, json=[{"number": 7}])
        return super().handle(request)


@pytest.mark.parametrize("trusted", [True, False])
@pytest.mark.parametrize("trigger", ["manual", "push", "completion"])
def test_collector_entrypoint_publishes_a_checkpoint_the_real_reader_accepts(tmp_path, monkeypatch, trusted, trigger):
    monkeypatch.chdir(tmp_path)
    subprocess.run(["git", "init", "-q"], check=True)
    write(tmp_path, "test_a.py", "def test_a(): pass\n")
    write(tmp_path, "test_b.py", "def test_b(): pass\n")
    head = commit(tmp_path)
    server = CollectionServer()
    server.ready()
    server.pr["merge_commit_sha"] = head
    event = "push" if trigger == "push" else "workflow_dispatch"
    server.runs[100] = {**server.runs[1], "id": 100, "event": event if trusted else "pull_request",
                        "head_branch": "main", "head_sha": head,
                        "created_at": datetime.now(timezone.utc).isoformat()}
    monkeypatch.setattr(promote_timings, "github_client", lambda: server.client)
    for name, value in {
        "GITHUB_RUN_ID": "100", "GITHUB_REF": "refs/heads/main", "GITHUB_REPOSITORY": "org/repo",
        "INPUT_HISTORY_BRANCH": "main", "INPUT_HISTORY_KEY": "unit", "INPUT_PRODUCER_WORKFLOW": "tests.yml",
        "INPUT_REQUIRED_GATES": '["Tests"]', "INPUT_PULL_REQUEST": "7" if trigger == "manual" else "0",
        "INPUT_SOURCE_RUN": "1" if trigger == "completion" else "0", "RUNNER_TEMP": str(tmp_path),
        "GITHUB_OUTPUT": str(tmp_path / "outputs"),
    }.items():
        monkeypatch.setenv(name, value)
    if not trusted:
        with pytest.raises(ValueError, match="trusted-branch"):
            promote_timings.main()
        assert not (tmp_path / "outputs").exists()
        return
    promote_timings.main()
    outputs = dict(line.split("=", 1) for line in (tmp_path / "outputs").read_text().splitlines())
    assert outputs["publish"] == "true"
    checkpoint = TimingHistory.model_validate_json(Path(outputs["history-path"]).read_bytes())
    assert checkpoint.producer_run_id == 100
    assert {entry.run_id for entry in checkpoint.imports.values()} == {1}
    uploaded = ArtifactServer({55: checkpoint})
    reader = uploaded.client()
    try:
        consumed = combine_histories(read_histories(reader, "unit", "main"), "unit", datetime.now(timezone.utc))
        assert consumed.observations["test_a.py"].seconds == 1
        assert consumed.imports == checkpoint.imports
        consumed.export(tmp_path / "planner.json")
        assert json.loads((tmp_path / "planner.json").read_text()) == {"test_a.py": 1}
    finally:
        reader.close()
