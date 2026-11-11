"""
Typed GitHub API adapter for CI observability.
"""

from __future__ import annotations

import base64
import io
import json
import os
import re
import zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from functools import cached_property
from time import perf_counter
from typing import Any, Literal, Self, overload

import httpx
import yaml
from pydantic import BaseModel, ConfigDict, TypeAdapter, ValidationError

from ci_esta.ci_observability.models import (
    GitHubCommitStatusV1,
    GitHubJobV1,
    GitHubPRDetailsV1,
    GitHubPullRequestV1,
    GitHubRunV1,
    StickySnapshotV1,
)
from ci_esta.ci_observability.workflow_graph import dependencies
from ci_esta.pagination import collect_pages


class GitHubJobsPageV1(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    jobs: list[GitHubJobV1]


class GitHubRunsPageV1(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    workflow_runs: list[GitHubRunV1]
    total_count: int | None = None


class GitHubRepositoryV1(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    default_branch: str


class WorkflowDispatch(BaseModel):
    ref: str
    inputs: dict[str, str | bool | int | float] = {}


class GitHubCommentAuthorV1(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    id: int
    type: str


class GitHubCommentV1(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    id: int
    body: str | None = None
    user: GitHubCommentAuthorV1 | None = None


class GitHubArtifactRunV1(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    id: int
    repository_id: int
    head_repository_id: int | None = None


class GitHubArtifactV1(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    id: int
    name: str
    expired: bool
    created_at: datetime
    workflow_run: GitHubArtifactRunV1 | None = None

    @property
    def from_same_repository(self) -> bool:
        """False for a fork's pull-request run, whose uploads land in the base repository."""
        run = self.workflow_run
        return run is not None and run.head_repository_id == run.repository_id


class GitHubArtifactsPageV1(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    artifacts: list[GitHubArtifactV1]


COMMENTS_ADAPTER = TypeAdapter(list[GitHubCommentV1])
STATUSES_ADAPTER = TypeAdapter(list[GitHubCommitStatusV1])
SNAPSHOT_PATTERN = re.compile(r"<!-- ci-observability-snapshot (?P<snapshot>\{.*?\}) -->")


class GitHubActionsClient:
    """
    Minimal typed client for run/job/status collection and sticky upsert.
    """

    def __init__(
        self,
        repository: str,
        token: str,
        api_url: str = "https://api.github.com",
        transport: httpx.BaseTransport | None = None,
        workflow_source_token: str = "",
    ) -> None:
        self._repository = repository
        self._workflow_source_token = workflow_source_token
        self._client = httpx.Client(
            base_url=api_url.rstrip("/"),
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            timeout=20.0,
            transport=transport,
        )

    @classmethod
    @overload
    def from_environment(cls, *, required: Literal[True] = True) -> Self: ...

    @classmethod
    @overload
    def from_environment(cls, *, required: Literal[False]) -> Self | None: ...

    @classmethod
    def from_environment(cls, *, required: bool = True) -> Self | None:
        repository = os.environ.get("GITHUB_REPOSITORY", "")
        token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN", "")
        if not repository or not token:
            if required:
                raise ValueError("GITHUB_REPOSITORY and GH_TOKEN or GITHUB_TOKEN are required")
            return None
        return cls(repository, token, os.environ.get("GITHUB_API_URL", "https://api.github.com"))

    def job_log(self, job_id: int) -> str:
        response = self._client.get(f"/repos/{self._repository}/actions/jobs/{job_id}/logs", follow_redirects=True)
        response.raise_for_status()
        return response.text

    def update_comment(self, comment_id: int, body: str) -> None:
        response = self._client.patch(f"/repos/{self._repository}/issues/comments/{comment_id}", json={"body": body})
        response.raise_for_status()

    def close(self) -> None:
        self._client.close()

    def get_run(self, run_id: int, *, run_attempt: int | None = None) -> GitHubRunV1:
        suffix = f"/attempts/{run_attempt}" if run_attempt is not None else ""
        response = self._client.get(f"/repos/{self._repository}/actions/runs/{run_id}{suffix}")
        response.raise_for_status()
        return GitHubRunV1.model_validate_json(response.content)

    def workflow_dependencies(self, run: GitHubRunV1,
                              jobs: list[GitHubJobV1] | None = None) -> dict[str, list[str]]:
        if not run.path or not re.fullmatch(r"\.github/workflows/[\w.-]+\.ya?ml", run.path):
            raise ValueError("Missing or unsupported source workflow path")
        skipped = {j.name for j in jobs or [] if j.conclusion == "skipped"}
        sources = {}

        def expand(repository: str, ref: str, path: str, prefix: str,
                   stack: tuple[str, ...]) -> dict[str, list[str]]:
            identity = f"{repository}/{path}@{ref}"
            if identity in stack or len(stack) >= 10:
                raise ValueError("Recursive or excessively nested reusable workflow")
            if identity not in sources:
                sources[identity] = self._workflow_source(repository, ref, path)

            def resolve(uses: str, child_prefix: str) -> dict[str, list[str]]:
                if uses.startswith("./"):
                    return expand(repository, ref, uses[2:], child_prefix, (*stack, identity))
                match = re.fullmatch(r"([\w.-]+/[\w.-]+)/(\.github/workflows/[\w.-]+\.ya?ml)@(.+)", uses)
                if match is None:
                    raise ValueError(f"Unsupported reusable workflow reference: {uses}")
                child_repo, child_path, child_ref = match.groups()
                recorded = {w.sha for w in run.referenced_workflows if w.path == uses}
                if len(recorded) == 1:
                    child_ref = recorded.pop()
                if not re.fullmatch(r"[0-9a-f]{40}", child_ref):
                    raise ValueError(f"No immutable source identity for reusable workflow: {uses}")
                return expand(child_repo, child_ref, child_path, child_prefix, (*stack, identity))

            return dependencies(sources[identity], resolve=resolve, skipped_calls=skipped, prefix=prefix)

        return expand(self._repository, run.head_sha, run.path, "", ())

    def _workflow_source(self, repository: str, ref: str, path: str) -> dict[str | bool, Any]:
        if not re.fullmatch(r"\.github/workflows/[\w.-]+\.ya?ml", path):
            raise ValueError("Unsupported reusable workflow path")
        headers = {}
        if repository != self._repository and self._workflow_source_token:
            headers["Authorization"] = f"Bearer {self._workflow_source_token}"
        response = self._client.get(f"/repos/{repository}/contents/{path}", params={"ref": ref}, headers=headers)
        response.raise_for_status()
        data = response.json()
        if data.get("encoding") != "base64" or data.get("size", 0) > 1_000_000:
            raise ValueError("Unsupported workflow content")
        content = base64.b64decode(data["content"])
        if len(content) > 1_000_000:
            raise ValueError("Workflow content is too large")
        return yaml.safe_load(content)

    def list_jobs(self, run_id: int | str, *, include_all_attempts: bool = False,
                  run_attempt: int | None = None) -> list[GitHubJobV1]:
        if include_all_attempts and run_attempt is not None:
            raise ValueError("an exact attempt cannot include all attempts")
        suffix = f"/attempts/{run_attempt}" if run_attempt is not None else ""
        def page(number: int) -> list[GitHubJobV1]:
            response = self._client.get(f"/repos/{self._repository}/actions/runs/{run_id}{suffix}/jobs",
                                       params={"filter": "all" if include_all_attempts else "latest", "per_page": 100, "page": number})
            response.raise_for_status()
            return GitHubJobsPageV1.model_validate_json(response.content).jobs
        return collect_pages(page)

    def list_overlapping_prior_runs(
        self,
        run: GitHubRunV1,
        pull_request_number: int,
    ) -> list[GitHubRunV1]:
        if run.workflow_id is None or run.head_branch is None:
            return []
        candidates: list[GitHubRunV1] = []
        page = 1
        while True:
            response = self._client.get(
                f"/repos/{self._repository}/actions/workflows/{run.workflow_id}/runs",
                params={
                    "branch": run.head_branch,
                    "event": run.event or "pull_request",
                    "per_page": 100,
                    "page": page,
                },
            )
            response.raise_for_status()
            batch = GitHubRunsPageV1.model_validate_json(response.content).workflow_runs
            candidates.extend(batch)
            if len(batch) < 100:
                break
            page += 1
        return [
            candidate
            for candidate in candidates
            if candidate.id != run.id
            and candidate.created_at < run.created_at
            and (
                candidate.status != "completed"
                or (candidate.updated_at is not None and candidate.updated_at > run.created_at)
            )
            and (
                not candidate.pull_requests
                or any(pull_request.number == pull_request_number for pull_request in candidate.pull_requests)
            )
        ]

    def default_branch(self) -> str:
        response = self._client.get(f"/repos/{self._repository}")
        response.raise_for_status()
        return GitHubRepositoryV1.model_validate_json(response.content).default_branch

    def pull_request(self, number: int) -> GitHubPRDetailsV1:
        response = self._client.get(f"/repos/{self._repository}/pulls/{number}")
        response.raise_for_status()
        return GitHubPRDetailsV1.model_validate_json(response.content)

    def pulls_for_commit(self, sha: str) -> list[GitHubPullRequestV1]:
        def page(number: int) -> list[GitHubPullRequestV1]:
            response = self._client.get(f"/repos/{self._repository}/commits/{sha}/pulls",
                                       params={"per_page": 100, "page": number})
            response.raise_for_status()
            return TypeAdapter(list[GitHubPullRequestV1]).validate_json(response.content)
        return collect_pages(page)

    def recent_closed_pulls(self, since: datetime, *, max_pages: int = 10) -> list[GitHubPRDetailsV1]:
        """Recover missed merge/completion events from GitHub's durable PR inventory."""
        result: list[GitHubPRDetailsV1] = []
        for page in range(1, max_pages + 1):
            response = self._client.get(f"/repos/{self._repository}/pulls", params={
                "state": "closed", "sort": "updated", "direction": "desc", "per_page": 100, "page": page,
            })
            response.raise_for_status()
            batch = TypeAdapter(list[GitHubPRDetailsV1]).validate_json(response.content)
            result.extend(pr for pr in batch if pr.updated_at >= since)
            if len(batch) < 100 or any(pr.updated_at < since for pr in batch):
                return result
        raise ValueError("closed PR inventory exceeds scan budget; narrow the lookback or increase max-pages")

    def runs_for_head(self, workflow: str, head_sha: str) -> list[GitHubRunV1]:
        """Enumerate every outcome. Never filter to success before selecting the last run."""
        result: list[GitHubRunV1] = []
        for page in range(1, 11):
            response = self._client.get(f"/repos/{self._repository}/actions/workflows/{workflow}/runs", params={
                "head_sha": head_sha, "event": "pull_request", "per_page": 100, "page": page,
            })
            response.raise_for_status()
            batch = GitHubRunsPageV1.model_validate_json(response.content)
            if batch.total_count is None or batch.total_count >= 1000:
                raise ValueError("cannot prove complete producer enumeration")
            result.extend(batch.workflow_runs)
            if len(batch.workflow_runs) < 100:
                if len(result) != batch.total_count:
                    raise ValueError("producer inventory changed during enumeration; retry")
                return result
        raise ValueError("producer inventory exceeds GitHub's 1000-run query limit")

    def workflow_source(self, workflow: str, ref: str) -> dict[str | bool, Any]:
        return self._workflow_source(self._repository, ref, f".github/workflows/{workflow}")

    def dispatch_workflow(self, workflow: str, request: WorkflowDispatch) -> None:
        response = self._client.post(
            f"/repos/{self._repository}/actions/workflows/{workflow}/dispatches", json=request.model_dump()
        )
        response.raise_for_status()

    def latest_successful_push_run(self, workflow_id: int, branch: str) -> GitHubRunV1 | None:
        """The newest green push run of a workflow on a branch: on the default branch, a full run."""
        response = self._client.get(
            f"/repos/{self._repository}/actions/workflows/{workflow_id}/runs",
            params={"branch": branch, "event": "push", "status": "success", "per_page": 1},
        )
        response.raise_for_status()
        runs = GitHubRunsPageV1.model_validate_json(response.content).workflow_runs
        return runs[0] if runs else None

    def list_commit_statuses(self, commit_sha: str) -> list[GitHubCommitStatusV1]:
        statuses: list[GitHubCommitStatusV1] = []
        page = 1
        while True:
            response = self._client.get(
                f"/repos/{self._repository}/commits/{commit_sha}/statuses",
                params={"per_page": 100, "page": page},
            )
            response.raise_for_status()
            batch = STATUSES_ADAPTER.validate_json(response.content)
            statuses.extend(batch)
            if len(batch) < 100:
                return statuses
            page += 1

    def list_artifacts(self, name: str | None, run_id: int | None = None) -> list[GitHubArtifactV1]:
        """Unexpired artifacts called `name`, newest first: one run's, or the whole repository's."""
        path = f"/actions/runs/{run_id}/artifacts" if run_id is not None else "/actions/artifacts"
        artifacts: list[GitHubArtifactV1] = []
        page = 1
        while True:
            response = self._client.get(
                f"/repos/{self._repository}{path}",
                params={"per_page": 100, "page": page, **({"name": name} if name is not None else {})}
            )
            response.raise_for_status()
            batch = GitHubArtifactsPageV1.model_validate_json(response.content).artifacts
            artifacts.extend(batch)
            if len(batch) < 100:
                break
            page += 1
        return sorted(
            (artifact for artifact in artifacts if not artifact.expired),
            key=lambda artifact: artifact.created_at,
            reverse=True,
        )

    def read_single_file_artifact(self, artifact_id: int, *, max_bytes: int = 10_000_000) -> bytes:
        """
        The one file in an artifact, whatever the uploader called it.

        The download redirects to blob storage; httpx drops the Authorization header when a
        redirect leaves the API origin, so the token never reaches it.
        """
        content = bytearray()
        with self._client.stream("GET", f"/repos/{self._repository}/actions/artifacts/{artifact_id}/zip",
                                 follow_redirects=True) as response:
            response.raise_for_status()
            for chunk in response.iter_bytes():
                content.extend(chunk)
                if len(content) > max_bytes:
                    raise ValueError("artifact exceeds compressed byte limit")
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            names = archive.namelist()
            if len(names) != 1:
                raise ValueError(f"artifact {artifact_id} holds {len(names)} files, expected one")
            if archive.getinfo(names[0]).file_size > max_bytes:
                raise ValueError("artifact exceeds uncompressed byte limit")
            return archive.read(names[0])

    def read_artifacts(self, artifact_ids: list[int]) -> list[bytes | Exception]:
        """Bound concurrent downloads; preserve input order and each artifact's failure."""
        if not artifact_ids:
            return []

        def read(identifier: int) -> bytes | Exception:
            try:
                return self.read_single_file_artifact(identifier)
            except Exception as error:
                return error

        started = perf_counter()
        with ThreadPoolExecutor(max_workers=min(4, len(artifact_ids))) as pool:
            results = list(pool.map(read, artifact_ids))
        print(json.dumps({"artifact_reads": len(results), "artifact_read_seconds": round(perf_counter() - started, 3),
                          "artifact_read_failures": sum(isinstance(item, Exception) for item in results)}))
        return results

    def list_comments(self, pull_request_number: int) -> list[GitHubCommentV1]:
        def page(number: int) -> list[GitHubCommentV1]:
            response = self._client.get(f"/repos/{self._repository}/issues/{pull_request_number}/comments",
                                       params={"per_page": 100, "page": number})
            response.raise_for_status()
            return COMMENTS_ADAPTER.validate_json(response.content)
        return collect_pages(page)

    _list_comments = list_comments

    def upsert_sticky(
        self,
        pull_request_number: int,
        marker: str,
        body: str,
        snapshot: StickySnapshotV1,
    ) -> int:
        def matching(comments):
            return [comment for comment in comments
                    if marker in (comment.body or "").splitlines()
                    and (comment.user is None or comment.user.type == "Bot"
                         or comment.user.id == self._authenticated_user_id)]

        comments = matching(self._list_comments(pull_request_number))
        if not comments:
            response = self._client.post(
                f"/repos/{self._repository}/issues/{pull_request_number}/comments",
                json={"body": body},
            )
            response.raise_for_status()
            created = GitHubCommentV1.model_validate_json(response.content)
            # Another first-time publisher may have created a comment after our lookup.
            comments = list({comment.id: comment for comment in
                             [created, *matching(self._list_comments(pull_request_number))]}.values())

        keeper = min(comments, key=lambda comment: comment.id)
        for comment in comments:
            previous = self._comment_snapshot(comment)
            if previous is not None and not snapshot.supersedes(previous):
                assert comment.body is not None, "a parsed snapshot requires a comment body"
                snapshot, body = previous, comment.body

        if keeper.body != body:
            response = self._client.patch(
                f"/repos/{self._repository}/issues/comments/{keeper.id}",
                json={"body": body},
            )
            response.raise_for_status()

        for duplicate in comments:
            if (duplicate.id != keeper.id and duplicate.user is not None
                    and duplicate.user == keeper.user and self._comment_snapshot(duplicate) is not None):
                response = self._client.delete(f"/repos/{self._repository}/issues/comments/{duplicate.id}")
                if response.status_code != 404:
                    response.raise_for_status()
        return keeper.id

    @cached_property
    def _authenticated_user_id(self) -> int | None:
        response = self._client.get("/user")
        # Installation tokens publish as a bot and cannot access the user endpoint.
        if response.status_code == 403:
            return None
        response.raise_for_status()
        return GitHubCommentAuthorV1.model_validate_json(response.content).id

    @staticmethod
    def _comment_snapshot(comment: GitHubCommentV1) -> StickySnapshotV1 | None:
        match = SNAPSHOT_PATTERN.search(comment.body or "")
        if match:
            try:
                return StickySnapshotV1.model_validate_json(match.group("snapshot"))
            except ValidationError:
                pass
        return None
