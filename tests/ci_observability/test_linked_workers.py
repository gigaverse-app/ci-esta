from datetime import datetime, timezone

import httpx
import pytest

from ci_esta.ci_observability.github import GitHubActionsClient, linked_worker_runs
from ci_esta.ci_observability.models import GitHubJobV1, GitHubRunV1


def parent_job(marker: str, conclusion: str = "success") -> GitHubJobV1:
    return GitHubJobV1.model_validate({
        "name": "router", "id": 9, "run_attempt": 2, "status": "completed",
        "steps": [{"number": 1, "name": marker, "conclusion": conclusion, "status": "completed"}],
    })


@pytest.mark.parametrize(("title", "head", "expected"), [
    ("CI worker for run 100 attempt 2", "abc", [23]),
    ("CI worker for run 100 attempt 1", "abc", []),
    ("CI worker for run 100 attempt 2", "moved", []),
])
def test_dispatched_cpu_belongs_to_the_parent_attempt_only_with_reciprocal_identity(
    title: str, head: str, expected: list[int],
) -> None:
    parent = GitHubRunV1(id=100, name="checks", run_attempt=2, status="completed",
                         head_sha="abc", created_at=datetime.now(timezone.utc))
    calls = []

    def respond(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if request.url.path.endswith("/attempts/1"):
            return httpx.Response(200, json={
                "id": 120, "name": "worker", "run_attempt": 1, "head_sha": head,
                "display_title": title, "event": "workflow_dispatch", "status": "completed",
                "created_at": parent.created_at.isoformat(), "repository": {"id": 7}, "head_repository": {"id": 7},
            })
        assert request.url.path.endswith("/runs/120/attempts/1/jobs")
        return httpx.Response(200, json={"jobs": [
            {"id": 23, "name": "worker", "run_attempt": 1, "status": "completed", "runner_name": "test-runner"},
            {"id": 24, "name": "never assigned", "status": "completed", "conclusion": "cancelled"},
        ]})

    client = GitHubActionsClient("org/repo", "unused", transport=httpx.MockTransport(respond))
    errors: list[str] = []
    coordinator = parent_job("CI worker run 120")
    children = linked_worker_runs(client, parent, [coordinator, coordinator, parent_job("CI worker run 999", "skipped")], errors)
    jobs = [job for child in children for job in child.jobs]
    assert [job.id for job in jobs] == expected
    assert bool(errors) is (not expected)
    if expected:
        assert len(calls) == 2
        assert jobs[0].source_run_id == 120
        assert jobs[0].parent_run_attempt == 2
        assert jobs[0].run_attempt == 1
