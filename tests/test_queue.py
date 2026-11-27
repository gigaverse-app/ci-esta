"""`ci-esta queue`: one job's runner wait, cache time and work time, for any repository."""

import json

import pytest

from ci_esta import cli
from ci_esta.lean import cli as lean_cli
from ci_esta.lean import queue_report

RUN = {"id": 7, "run_attempt": 1, "event": "pull_request", "created_at": "2026-11-27T10:00:00Z"}
STEPS = [
    ("Restore uv cache", "2026-11-27T10:05:00Z", "2026-11-27T10:05:40Z"),
    ("Restore node_modules", "2026-11-27T10:05:40Z", "2026-11-27T10:06:00Z"),
    ("Run tests", "2026-11-27T10:06:00Z", "2026-11-27T10:08:00Z"),
]
JOB = {
    "id": 70, "name": "tests", "status": "completed", "conclusion": "failure", "labels": ["self-hosted", "big"],
    "created_at": "2026-11-27T10:00:10Z", "started_at": "2026-11-27T10:05:00Z", "completed_at": "2026-11-27T10:08:10Z",
    "steps": [
        {"name": name, "status": "completed", "conclusion": "success", "started_at": start, "completed_at": end}
        for name, start, end in STEPS
    ],
}  # fmt: skip
OTHER = {**JOB, "id": 71, "name": "lint"}


@pytest.fixture
def github(monkeypatch):
    """Answer `gh api` from one completed pull-request run with two jobs; record the paths requested."""
    requested = []

    def check_output(command, text):
        path = command[-1]
        requested.append(path)
        if "/jobs" in path:
            return json.dumps({"jobs": [JOB, OTHER]})
        completed = "event=pull_request&status=completed" in path
        return json.dumps({"total_count": int(completed), "workflow_runs": [RUN] if completed else []})

    monkeypatch.setattr(queue_report.subprocess, "check_output", check_output)
    return requested


def test_queue_measures_the_named_job_of_any_workflow(github, capsys):
    command = ["queue", "--repo", "acme/app", "--workflow", "ci.yml", "--job", "tests", "--work-step", "Run tests"]
    caches = ["--cache-step", "Restore uv cache", "--cache-step", "Restore node_modules"]
    assert cli.main([*command, *caches]) == 0
    report = json.loads(capsys.readouterr().out)
    assert (report["repository"], report["workflow"], report["job"]) == ("acme/app", "ci.yml", "tests")
    assert [row["job_id"] for row in report["jobs"]] == [70]
    (group,) = report["groups"]
    assert (group["event"], group["pool"]) == ("pull_request", "big,self-hosted")
    assert {key: group[key]["median_s"] for key in ("queue_s", "cache_s", "work_s", "job_s", "verdict_s")} == {
        "queue_s": 290, "cache_s": 60, "work_s": 120, "job_s": 190, "verdict_s": 490,
    }  # fmt: skip
    assert "repos/acme/app/actions/workflows/ci.yml/runs?event=pull_request&status=completed&per_page=20" in github
    assert "repos/acme/app/actions/runs/7/attempts/1/jobs?per_page=100" in github

    assert cli.main([*command, "--pool", "big", "--pool", "small"]) == 0
    (group,) = json.loads(capsys.readouterr().out)["groups"]
    assert (group["pool"], group["cache_s"]) == ("big", {"n": 0})


def test_queue_requires_the_repository_workflow_and_job(capsys):
    with pytest.raises(SystemExit) as error:
        cli.main(["queue", "--repo", "acme/app"])
    assert error.value.code == 2
    assert "--workflow, --job" in capsys.readouterr().err


def test_lean_queue_keeps_its_defaults_and_report_keys(github, capsys):
    assert lean_cli.main(["queue"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["repository"] == "leanprover-community/riemann-hypothesis"
    assert report["jobs"] == [] and report["groups"] == []
    assert any("workflows/build.yml/runs" in path for path in github)
    assert lean_cli.main(["queue", "--job", "tests", "--work-step", "Run tests"]) == 0
    (group,) = json.loads(capsys.readouterr().out)["groups"]
    assert (group["pool"], group["proof_s"]["median_s"]) == ("other", 120)
