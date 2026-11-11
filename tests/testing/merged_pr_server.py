"""GitHub HTTP boundary fixture, shared by integration and model trace replays."""

import io
import json
import zipfile
from datetime import datetime, timedelta, timezone

import httpx

from ci_esta.ci_observability.github import GitHubActionsClient
from ci_esta.measurements import MeasurementIdentity
from ci_esta.testing.merged_pr_timings import PromotionPolicy, TimingMeasurements, automatic_name, measurement_name

REPOSITORY = "org/repo"
NOW = datetime(2026, 11, 11, tzinfo=timezone.utc)
POLICY = PromotionPolicy(repository=REPOSITORY, workflow="tests.yml", key="unit", gates={"Tests"})


class MergedPRServer:
    """Events mutate remote API data only; admission remains in production code."""

    def __init__(self):
        self.tick = 0
        self.head = 1
        self.runs = {}
        self.attempts = {}
        self.jobs = {}
        self.artifacts = {}
        self.payloads = {}
        self.pr = dict(number=7, updated_at=NOW.isoformat(), merged_at=None, merge_commit_sha=None,
                       base=dict(ref="main", sha="b" * 40, repo=dict(full_name=REPOSITORY)), head=self.ref())
        self.client = GitHubActionsClient(REPOSITORY, "fake", transport=httpx.MockTransport(self.handle))

    def ref(self):
        return dict(ref="feature", sha=str(self.head) * 40, repo=dict(full_name=REPOSITORY))

    def time(self):
        self.tick += 1
        return (NOW + timedelta(seconds=self.tick)).isoformat()

    def push(self):
        self.head += 1
        self.pr["head"] = self.ref()

    def start(self):
        number = len(self.runs) + 1
        self.runs[number] = dict(id=number, name="Tests", run_attempt=1, event="pull_request",
                                 status="in_progress", conclusion=None, head_sha=self.ref()["sha"],
                                 head_branch="feature", created_at=self.time(), path=".github/workflows/tests.yml")
        self.jobs[number] = [dict(id=number, name="Tests", run_attempt=1, status="in_progress", conclusion=None,
                                  steps=[dict(name=f'PR evidence #7 head {self.ref()["sha"]}',
                                              number=1, status="completed", conclusion="success")])]

    def pass_gate(self, number):
        if self.jobs[number][0]["conclusion"] != "success":
            self.jobs[number][0].update(status="completed", conclusion="success", completed_at=self.time())

    def rerun(self, number):
        run = self.runs[number]
        self.attempts[number, run["run_attempt"]] = dict(run)
        run.update(run_attempt=run["run_attempt"] + 1, run_started_at=self.time(),
                   status="in_progress", conclusion=None)
        self.jobs[number][0].update(run_attempt=run["run_attempt"], status="in_progress",
                                    conclusion=None, completed_at=None)

    def finish(self, number, result):
        self.runs[number].update(status="completed", conclusion=result, updated_at=self.time())

    def merge(self):
        self.pr.update(merged_at=self.time(), merge_commit_sha="c" * 40)

    def upload(self, number, artifact="valid", *, automatic=False):
        run = self.runs[number]
        measured = TimingMeasurements(key="unit", run_id=number, attempt=run["run_attempt"],
                                      head_sha=run["head_sha"], complete_files=True, report_count=1,
                                      observed_at=run["created_at"], durations={"test_a.py": number},
                                      origin=MeasurementIdentity(run_id=number, run_attempt=run["run_attempt"],
                                                                 head_sha=run["head_sha"]) if automatic else None,
                                      pull_request=7 if automatic else None)
        payload = measured.model_dump(mode="json")
        if artifact == "invalid":
            payload["head_sha"] = "f" * 40
        self.payloads[number] = payload
        self.artifacts[number] = dict(id=number, name=measurement_name("unit", "all", number, run["run_attempt"]),
                                      expired=False, created_at=self.time(),
                                      workflow_run=dict(id=number, repository_id=1, head_repository_id=1))
        if automatic:
            self.artifacts[number]["name"] = automatic_name("unit", "file-costs")

    def expire(self, number):
        self.artifacts[number]["expired"] = True

    def ready(self):
        self.start()
        self.pass_gate(1)
        self.finish(1, "success")
        self.upload(1)
        self.merge()

    def handle(self, request):
        path = request.url.path
        if path.endswith("/actions/artifacts"):
            name = request.url.params.get("name")
            return httpx.Response(200, json={"artifacts": [artifact for artifact in self.artifacts.values()
                                                          if name is None or artifact["name"] == name]})
        if "/commits/" in path and path.endswith("/pulls"):
            return httpx.Response(200, json=[{"number": 7}])
        if path.endswith("/pulls/7"):
            return httpx.Response(200, json=self.pr)
        if "/workflows/" in path:
            runs = [run for run in self.runs.values() if run["head_sha"] == request.url.params["head_sha"]]
            return httpx.Response(200, json=dict(workflow_runs=runs, total_count=len(runs)))
        if path.endswith("/zip"):
            number = int(path.split("/")[-2])
            content = io.BytesIO()
            with zipfile.ZipFile(content, "w") as archive:
                archive.writestr("measured.json", json.dumps(self.payloads[number]))
            return httpx.Response(200, content=content.getvalue())
        if "/runs/" in path:
            parts = path.split("/")
            number = int(parts[parts.index("runs") + 1])
            if path.endswith("/jobs"):
                return httpx.Response(200, json=dict(jobs=self.jobs[number]))
            if path.endswith("/artifacts"):
                return httpx.Response(200, json=dict(artifacts=[artifact for artifact in self.artifacts.values()
                                                               if artifact["workflow_run"]["id"] == number]))
            if "attempts" in parts:
                attempt = int(parts[parts.index("attempts") + 1])
                return httpx.Response(200, json=self.attempts.get((number, attempt), self.runs[number]))
            return httpx.Response(200, json=self.runs[number])
        raise AssertionError(f"Unexpected HTTP request: {request.method} {request.url}")

    def close(self):
        self.client.close()
