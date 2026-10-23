import base64
import io
import zipfile
from datetime import datetime, timezone

import httpx
import pytest
from pytest_selective.impact_models import ExplanationUnavailable

from ci_esta.ci_observability.github import (
    GitHubActionsClient,
    GitHubArtifactsPageV1,
    GitHubArtifactV1,
    GitHubCommentV1,
    GitHubJobsPageV1,
    GitHubRunsPageV1,
)
from ci_esta.ci_observability.models import (
    GitHubCommitStatusV1,
    GitHubJobV1,
    GitHubPullRequestV1,
    GitHubRunV1,
    StickySnapshotV1,
)
from tests.ci_observability.builders import artifact

REPOSITORY = "gigaverse-app/example"
TOKEN = "test-token"
API_URL = "https://api.github.test"
RUN_ID = 123
RUN_ATTEMPT = 2
JOB_COUNT = 101
PAGE_SIZE = 100
COMMENT_ID = 77
PR_NUMBER = 86
MARKER = "<!-- marker -->"
NOW = datetime(2026, 7, 23, 6, 0, 0, tzinfo=timezone.utc)
HEAD_SHA = "a" * 40
WORKFLOW_NAME = "Primary CI"
WORKFLOW_ID = 30095599
BRANCH = "agent/example"
BEFORE_NOW = datetime(2026, 7, 23, 5, 59, 59, tzinfo=timezone.utc)
AFTER_NOW = datetime(2026, 7, 23, 6, 0, 1, tzinfo=timezone.utc)


def test_exact_attempt_endpoints_preserve_historical_report_identity():
    def respond(request):
        prefix = f"/repos/{REPOSITORY}/actions/runs/{RUN_ID}/attempts/1"
        if request.url.path == prefix:
            return httpx.Response(200, json={"id": RUN_ID, "name": "CI", "run_attempt": 1,
                "status": "completed", "created_at": NOW.isoformat(), "head_sha": HEAD_SHA})
        assert request.url.path == prefix + "/jobs"
        return httpx.Response(200, json={"total_count": 0, "jobs": []})

    client = GitHubActionsClient(REPOSITORY, TOKEN, API_URL, transport=httpx.MockTransport(respond))
    try:
        assert client.get_run(RUN_ID, run_attempt=1).run_attempt == 1
        assert client.list_jobs(RUN_ID, include_all_attempts=False, run_attempt=1) == []
        with pytest.raises(ValueError):
            client.list_jobs(RUN_ID, include_all_attempts=True, run_attempt=1)
    finally:
        client.close()


def test_workflow_topology_reads_only_the_reported_commit_as_data():
    def respond(request):
        assert request.url.path == f"/repos/{REPOSITORY}/contents/.github/workflows/ci.yml"
        assert request.url.params["ref"] == HEAD_SHA
        source = b"jobs:\n  test:\n    steps: [{run: NEVER_EXECUTE_THIS}]\n  gate:\n    needs: test\n"
        return httpx.Response(200, json={"encoding": "base64", "size": len(source),
                                        "content": base64.b64encode(source).decode()})

    client = GitHubActionsClient(REPOSITORY, TOKEN, API_URL, transport=httpx.MockTransport(respond))
    run = GitHubRunV1(id=RUN_ID, name="CI", run_attempt=1, status="completed", created_at=NOW,
                      head_sha=HEAD_SHA, path=".github/workflows/ci.yml")
    try:
        assert client.workflow_dependencies(run) == {"test": [], "gate": ["test"]}
    finally:
        client.close()


@pytest.mark.parametrize("reference,recorded", [("main", True), ("b" * 40, False)])
def test_nested_sources_use_recorded_immutable_refs(reference, recorded):
    child_sha = "b" * 40
    uses = f"other/project/.github/workflows/child.yml@{reference}"
    sources = {
        (REPOSITORY, ".github/workflows/ci.yml", HEAD_SHA):
            f"jobs:\n  plan: {{}}\n  call:\n    needs: plan\n    uses: {uses}\n  gate:\n    needs: call\n",
        ("other/project", ".github/workflows/child.yml", child_sha):
            "jobs:\n  checks:\n    uses: ./.github/workflows/inner.yml\n",
        ("other/project", ".github/workflows/inner.yml", child_sha):
            "jobs:\n  tests: {}\n",
    }

    def respond(request):
        repo, path = request.url.path.removeprefix("/repos/").split("/contents/")
        source = sources[(repo, path, request.url.params["ref"])].encode()
        return httpx.Response(200, json={"encoding": "base64", "size": len(source),
                                        "content": base64.b64encode(source).decode()})

    client = GitHubActionsClient(REPOSITORY, TOKEN, API_URL, transport=httpx.MockTransport(respond))
    run = GitHubRunV1(id=RUN_ID, name="CI", run_attempt=1, status="completed", created_at=NOW,
                     head_sha=HEAD_SHA, path=".github/workflows/ci.yml",
                     referenced_workflows=[{"path": uses, "sha": child_sha}] if recorded else [])
    try:
        assert client.workflow_dependencies(run) == {
            "plan": [], "call / checks / tests": ["plan"], "gate": ["call / checks / tests"]}
    finally:
        client.close()


def test_mutable_reusable_reference_without_run_identity_is_not_guessed():
    source = b"jobs:\n  call:\n    uses: other/project/.github/workflows/child.yml@main\n"
    client = GitHubActionsClient(REPOSITORY, TOKEN, API_URL, transport=httpx.MockTransport(
        lambda _: httpx.Response(200, json={"encoding": "base64", "size": len(source),
                                          "content": base64.b64encode(source).decode()})))
    run = GitHubRunV1(id=RUN_ID, name="CI", run_attempt=1, status="completed", created_at=NOW,
                     head_sha=HEAD_SHA, path=".github/workflows/ci.yml")
    try:
        with pytest.raises(ValueError, match="No immutable source identity"):
            client.workflow_dependencies(run)
    finally:
        client.close()


def test_private_workflow_source_token_is_scoped_to_external_content_reads():
    seen = []

    def respond(request):
        seen.append((request.url.path, request.headers["Authorization"]))
        if "/contents/" not in request.url.path:
            return httpx.Response(200, json={"jobs": []})
        source = b"jobs:\n  test: {}\n"
        return httpx.Response(200, json={"encoding": "base64", "size": len(source),
                                        "content": base64.b64encode(source).decode()})

    client = GitHubActionsClient(REPOSITORY, TOKEN, API_URL,
                                transport=httpx.MockTransport(respond),
                                workflow_source_token="read-private-sources")
    try:
        client._workflow_source(REPOSITORY, HEAD_SHA, ".github/workflows/ci.yml")
        client._workflow_source("other/private", HEAD_SHA, ".github/workflows/ci.yml")
        client.list_jobs(RUN_ID, include_all_attempts=False)
    finally:
        client.close()
    assert [token for _, token in seen] == [f"Bearer {TOKEN}", "Bearer read-private-sources", f"Bearer {TOKEN}"]


def _snapshot(
    *,
    completed_gates: int,
    observed_at: datetime = NOW,
) -> StickySnapshotV1:
    return StickySnapshotV1(
        run_id=RUN_ID,
        run_attempt=RUN_ATTEMPT,
        completed_gates=completed_gates,
        observed_at=observed_at,
    )


def _job(job_id: int) -> GitHubJobV1:
    return GitHubJobV1(
        id=job_id,
        name=f"job-{job_id}",
        run_attempt=RUN_ATTEMPT,
        status="completed",
        conclusion="success",
        started_at=NOW,
        completed_at=NOW,
    )


def test_client_validates_run_paginated_jobs_and_statuses() -> None:
    run = GitHubRunV1(
        id=RUN_ID,
        name=WORKFLOW_NAME,
        run_attempt=RUN_ATTEMPT,
        status="completed",
        conclusion="success",
        created_at=NOW,
        run_started_at=NOW,
        head_sha=HEAD_SHA,
    )
    jobs = [_job(job_id) for job_id in range(JOB_COUNT)]
    statuses = [
        GitHubCommitStatusV1(
            context=f"required-{index}",
            state="success",
            created_at=NOW,
            updated_at=NOW,
        )
        for index in range(JOB_COUNT)
    ]
    observed_filters: list[str] = []
    observed_status_pages: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith(f"/actions/runs/{RUN_ID}"):
            return httpx.Response(200, json=run.model_dump(mode="json"))
        if request.url.path.endswith(f"/actions/runs/{RUN_ID}/jobs"):
            observed_filters.append(request.url.params["filter"])
            page = int(request.url.params["page"])
            start = (page - 1) * PAGE_SIZE
            payload = GitHubJobsPageV1(jobs=jobs[start : start + PAGE_SIZE])
            return httpx.Response(200, json=payload.model_dump(mode="json"))
        if request.url.path.endswith(f"/commits/{HEAD_SHA}/statuses"):
            page = int(request.url.params["page"])
            observed_status_pages.append(page)
            start = (page - 1) * PAGE_SIZE
            payload = statuses[start : start + PAGE_SIZE]
            return httpx.Response(
                200,
                json=[status.model_dump(mode="json") for status in payload],
            )
        raise AssertionError(f"unexpected request: {request.url}")

    client = GitHubActionsClient(
        REPOSITORY,
        TOKEN,
        API_URL,
        transport=httpx.MockTransport(handler),
    )
    try:
        assert client.get_run(RUN_ID) == run
        assert client.list_jobs(RUN_ID, include_all_attempts=False) == jobs
        assert client.list_jobs(RUN_ID, include_all_attempts=True) == jobs
        assert client.list_commit_statuses(HEAD_SHA) == statuses
    finally:
        client.close()

    assert observed_filters == ["latest", "latest", "all", "all"]
    assert observed_status_pages == [1, 2]


def test_client_finds_paginated_same_pr_runs_overlapping_current_creation() -> None:
    current = GitHubRunV1(
        id=RUN_ID,
        name=WORKFLOW_NAME,
        workflow_id=WORKFLOW_ID,
        run_attempt=RUN_ATTEMPT,
        event="pull_request",
        status="in_progress",
        created_at=NOW,
        updated_at=AFTER_NOW,
        run_started_at=NOW,
        head_branch=BRANCH,
        head_sha=HEAD_SHA,
        pull_requests=[GitHubPullRequestV1(number=PR_NUMBER)],
    )
    non_overlapping = [current.model_copy(update={"id": index + 1000}) for index in range(PAGE_SIZE)]
    overlapping = current.model_copy(
        update={
            "id": RUN_ID - 1,
            "status": "completed",
            "conclusion": "cancelled",
            "created_at": BEFORE_NOW,
            "updated_at": AFTER_NOW,
            # GitHub can omit this association in workflow-run listings. The
            # workflow, event, and exact head branch still identify the run.
            "pull_requests": [],
        }
    )
    different_pr = overlapping.model_copy(
        update={
            "id": RUN_ID - 2,
            "pull_requests": [GitHubPullRequestV1(number=PR_NUMBER + 1)],
        }
    )
    candidates = [*non_overlapping, overlapping, different_pr]
    observed_pages: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        observed_pages.append(int(request.url.params["page"]))
        page = int(request.url.params["page"])
        start = (page - 1) * PAGE_SIZE
        payload = GitHubRunsPageV1(workflow_runs=candidates[start : start + PAGE_SIZE])
        return httpx.Response(200, json=payload.model_dump(mode="json"))

    client = GitHubActionsClient(
        REPOSITORY,
        TOKEN,
        API_URL,
        transport=httpx.MockTransport(handler),
    )
    try:
        result = client.list_overlapping_prior_runs(current, PR_NUMBER)
    finally:
        client.close()

    assert result == [overlapping]
    assert observed_pages == [1, 2]


def test_client_updates_existing_marker_comment() -> None:
    requests: list[httpx.Request] = []
    previous_snapshot = _snapshot(completed_gates=1)
    existing = GitHubCommentV1(
        id=COMMENT_ID,
        body=(f"old\n{MARKER}\n<!-- ci-observability-snapshot {previous_snapshot.model_dump_json()} -->"),
    )
    updated = GitHubCommentV1(id=COMMENT_ID, body=f"new\n{MARKER}")
    first_page = [GitHubCommentV1(id=index, body="unrelated") for index in range(PAGE_SIZE)]

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method == "GET":
            comments = first_page if request.url.params["page"] == "1" else [existing]
            return httpx.Response(
                200,
                json=[comment.model_dump(mode="json") for comment in comments],
            )
        return httpx.Response(200, json=updated.model_dump(mode="json"))

    client = GitHubActionsClient(
        REPOSITORY,
        TOKEN,
        API_URL,
        transport=httpx.MockTransport(handler),
    )
    try:
        assert (
            client.upsert_sticky(
                PR_NUMBER,
                MARKER,
                updated.body or "",
                _snapshot(completed_gates=2),
            )
            == COMMENT_ID
        )
    finally:
        client.close()

    assert [request.method for request in requests] == ["GET", "GET", "PATCH"]
    assert requests[-1].url.path.endswith(f"/issues/comments/{COMMENT_ID}")


def test_client_creates_marker_comment_when_absent() -> None:
    requests: list[httpx.Request] = []
    created = GitHubCommentV1(id=COMMENT_ID, body=MARKER)

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method == "GET":
            return httpx.Response(200, json=[])
        return httpx.Response(201, json=created.model_dump(mode="json"))

    client = GitHubActionsClient(
        REPOSITORY,
        TOKEN,
        API_URL,
        transport=httpx.MockTransport(handler),
    )
    try:
        assert (
            client.upsert_sticky(
                PR_NUMBER,
                MARKER,
                MARKER,
                _snapshot(completed_gates=1),
            )
            == COMMENT_ID
        )
    finally:
        client.close()

    assert [request.method for request in requests] == ["GET", "POST"]
    assert requests[-1].url.path.endswith(f"/issues/{PR_NUMBER}/comments")


def test_client_does_not_replace_a_more_complete_same_run_snapshot() -> None:
    requests: list[httpx.Request] = []
    previous_snapshot = _snapshot(completed_gates=2)
    existing = GitHubCommentV1(
        id=COMMENT_ID,
        body=(f"{MARKER}\n<!-- ci-observability-snapshot {previous_snapshot.model_dump_json()} -->"),
    )

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=[existing.model_dump(mode="json")])

    client = GitHubActionsClient(
        REPOSITORY,
        TOKEN,
        API_URL,
        transport=httpx.MockTransport(handler),
    )
    try:
        comment_id = client.upsert_sticky(
            PR_NUMBER,
            MARKER,
            MARKER,
            _snapshot(completed_gates=1),
        )
    finally:
        client.close()

    assert comment_id == COMMENT_ID
    assert [request.method for request in requests] == ["GET"]


ARTIFACT_NAME = "test-impact-explanation"
BLOB_HOST = "blobs.example.test"
OLDER = datetime(2026, 7, 22, 6, 0, 0, tzinfo=timezone.utc)
EXPLANATION = ExplanationUnavailable(unavailable="complete suite fallback").model_dump_json().encode()
ARTIFACT_PAGE = 100


def _zip(files: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    return buffer.getvalue()


def _page(artifacts: list[GitHubArtifactV1]) -> httpx.Response:
    return httpx.Response(200, json=GitHubArtifactsPageV1(artifacts=artifacts).model_dump(mode="json"))


@pytest.mark.parametrize(
    ("run_id", "path"),
    [
        (RUN_ID, f"/repos/{REPOSITORY}/actions/runs/{RUN_ID}/artifacts"),
        (None, f"/repos/{REPOSITORY}/actions/artifacts"),
    ],
    ids=["one-run", "whole-repository"],
)
def test_client_lists_unexpired_artifacts_newest_first(run_id: int | None, path: str) -> None:
    requests: list[httpx.Request] = []
    older, newer = artifact(1, RUN_ID, created_at=OLDER), artifact(2, RUN_ID, created_at=NOW)
    expired = artifact(3, RUN_ID, created_at=NOW, expired=True)

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return _page([older, expired, newer])

    client = GitHubActionsClient(REPOSITORY, TOKEN, API_URL, transport=httpx.MockTransport(handler))
    try:
        assert [item.id for item in client.list_artifacts(ARTIFACT_NAME, run_id=run_id)] == [2, 1]
    finally:
        client.close()

    assert requests[0].url.path == path
    assert requests[0].url.params["name"] == ARTIFACT_NAME


def test_client_reads_every_page_of_artifacts() -> None:
    first_page = [artifact(number, RUN_ID, created_at=OLDER) for number in range(ARTIFACT_PAGE)]
    newest = artifact(ARTIFACT_PAGE, RUN_ID, created_at=NOW)

    def handler(request: httpx.Request) -> httpx.Response:
        return _page(first_page if request.url.params["page"] == "1" else [newest])

    client = GitHubActionsClient(REPOSITORY, TOKEN, API_URL, transport=httpx.MockTransport(handler))
    try:
        listed = client.list_artifacts(ARTIFACT_NAME)
    finally:
        client.close()

    assert len(listed) == ARTIFACT_PAGE + 1
    assert listed[0] == newest


def test_client_reads_an_artifact_through_the_blob_redirect_without_sending_the_token() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.host == BLOB_HOST:
            return httpx.Response(200, content=_zip({"any-name.json": EXPLANATION}))
        return httpx.Response(302, headers={"Location": f"https://{BLOB_HOST}/signed"})

    client = GitHubActionsClient(REPOSITORY, TOKEN, API_URL, transport=httpx.MockTransport(handler))
    try:
        assert client.read_single_file_artifact(COMMENT_ID) == EXPLANATION
    finally:
        client.close()

    api_request, blob_request = requests
    assert api_request.url.path == f"/repos/{REPOSITORY}/actions/artifacts/{COMMENT_ID}/zip"
    assert api_request.headers["Authorization"] == f"Bearer {TOKEN}"
    assert "Authorization" not in blob_request.headers


def test_client_rejects_an_artifact_that_is_not_one_file() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=_zip({"a.json": EXPLANATION, "b.json": EXPLANATION}))

    client = GitHubActionsClient(REPOSITORY, TOKEN, API_URL, transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(ValueError, match="holds 2 files"):
            client.read_single_file_artifact(COMMENT_ID)
    finally:
        client.close()


@pytest.mark.parametrize(("fork", "same"), [(False, True), (True, False)], ids=["branch", "fork"])
def test_artifacts_from_fork_pull_requests_are_not_from_the_same_repository(fork: bool, same: bool) -> None:
    assert artifact(1, RUN_ID, fork=fork).from_same_repository is same
    assert GitHubArtifactV1(id=1, name=ARTIFACT_NAME, expired=False, created_at=NOW).from_same_repository is False
