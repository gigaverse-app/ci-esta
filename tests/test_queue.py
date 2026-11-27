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


def test_queue_samples_the_events_named(monkeypatch, capsys):
    """A workflow other workflows dispatch has no pull_request, merge_group or push run to sample."""
    requested = []

    def check_output(command, text):
        requested.append(command[-1])
        if "/jobs" in command[-1]:
            return json.dumps({"jobs": [JOB]})
        dispatched = "event=workflow_dispatch&status=completed" in command[-1]
        runs = [{**RUN, "event": "workflow_dispatch"}] if dispatched else []
        return json.dumps({"total_count": len(runs), "workflow_runs": runs})

    monkeypatch.setattr(queue_report.subprocess, "check_output", check_output)
    command = ["queue", "--repo", "acme/app", "--workflow", "arc-capacity-request.yaml", "--job", "tests"]
    assert cli.main(command) == 0
    out, err = capsys.readouterr()
    assert json.loads(out)["jobs"] == []
    assert err == (
        "ci-esta queue: arc-capacity-request.yaml has no runs started by pull_request, merge_group, push; "
        "name the events that start it with --event\n"
    )

    requested.clear()
    assert cli.main([*command, "--event", "workflow_dispatch", "--event", "schedule"]) == 0
    out, err = capsys.readouterr()
    report = json.loads(out)
    assert report["sampled_completed_workflows"] == {"workflow_dispatch": 1, "schedule": 0}
    assert [(group["event"], group["queue_s"]["median_s"]) for group in report["groups"]] == [("workflow_dispatch", 290)]
    assert err == ""
    assert not any("event=pull_request" in path or "event=push" in path for path in requested)


def test_queue_reads_every_page_of_a_run_with_more_than_100_jobs(monkeypatch, capsys):
    shards = [{**JOB, "id": 1000 + index, "name": f"shard {index}"} for index in range(100)]

    def check_output(command, text):
        path = command[-1]
        if "/jobs" in path:
            return json.dumps({"jobs": [JOB] if path.endswith("&page=2") else shards})
        completed = "event=pull_request&status=completed" in path
        return json.dumps({"total_count": int(completed), "workflow_runs": [RUN] if completed else []})

    monkeypatch.setattr(queue_report.subprocess, "check_output", check_output)
    assert cli.main(["queue", "--repo", "acme/app", "--workflow", "ci.yml", "--job", "tests"]) == 0
    assert [row["job_id"] for row in json.loads(capsys.readouterr().out)["jobs"]] == [70]


def test_queue_names_the_jobs_it_saw_when_none_has_the_name(github, capsys):
    assert cli.main(["queue", "--repo", "acme/app", "--workflow", "ci.yml", "--job", "Tests"]) == 0
    out, err = capsys.readouterr()
    assert json.loads(out)["jobs"] == []
    assert err == "ci-esta queue: no job named 'Tests' in the sampled runs; their jobs: lint, tests\n"


def test_queue_reports_a_failed_github_request_without_a_traceback(monkeypatch, capsys):
    def check_output(command, text):
        raise queue_report.subprocess.CalledProcessError(1, command)

    monkeypatch.setattr(queue_report.subprocess, "check_output", check_output)
    with pytest.raises(SystemExit) as error:
        cli.main(["queue", "--repo", "acme/app", "--workflow", "missing.yml", "--job", "tests"])
    assert error.value.code == 1
    out, err = capsys.readouterr()
    assert out == ""
    assert err.startswith("ci-esta queue: gh api repos/acme/app/actions/workflows/missing.yml/runs?event=")
    assert err.endswith(" failed; check --repo and --workflow\n")
