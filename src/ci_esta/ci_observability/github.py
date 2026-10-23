"""
Typed GitHub API adapter for CI observability.
"""

from __future__ import annotations

import base64
import io
import re
import zipfile
from datetime import datetime

import httpx
import yaml
from pydantic import BaseModel, ConfigDict, TypeAdapter

from ci_esta.ci_observability.models import (
    GitHubCommitStatusV1,
    GitHubJobV1,
    GitHubRunV1,
    StickySnapshotV1,
)
from ci_esta.ci_observability.workflow_graph import dependencies


class GitHubJobsPageV1(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    jobs: list[GitHubJobV1]


class GitHubRunsPageV1(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    workflow_runs: list[GitHubRunV1]


class GitHubRepositoryV1(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    default_branch: str


class GitHubCommentV1(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    id: int
    body: str | None = None


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
    ) -> None:
        self._repository = repository
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

    def _workflow_source(self, repository: str, ref: str, path: str) -> dict:
        if not re.fullmatch(r"\.github/workflows/[\w.-]+\.ya?ml", path):
            raise ValueError("Unsupported reusable workflow path")
        response = self._client.get(f"/repos/{repository}/contents/{path}", params={"ref": ref})
        response.raise_for_status()
        data = response.json()
        if data.get("encoding") != "base64" or data.get("size", 0) > 1_000_000:
            raise ValueError("Unsupported workflow content")
        content = base64.b64decode(data["content"])
        if len(content) > 1_000_000:
            raise ValueError("Workflow content is too large")
        return yaml.safe_load(content)

    def list_jobs(
        self, run_id: int, *, include_all_attempts: bool, run_attempt: int | None = None
    ) -> list[GitHubJobV1]:
        if include_all_attempts and run_attempt is not None:
            raise ValueError("an exact attempt cannot include all attempts")
        suffix = f"/attempts/{run_attempt}" if run_attempt is not None else ""
        attempt_filter = "all" if include_all_attempts else "latest"
        jobs: list[GitHubJobV1] = []
        page = 1
        while True:
            response = self._client.get(
                f"/repos/{self._repository}/actions/runs/{run_id}{suffix}/jobs",
                params={"filter": attempt_filter, "per_page": 100, "page": page},
            )
            response.raise_for_status()
            batch = GitHubJobsPageV1.model_validate_json(response.content).jobs
            jobs.extend(batch)
            if len(batch) < 100:
                return jobs
            page += 1

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

    def list_artifacts(self, name: str, run_id: int | None = None) -> list[GitHubArtifactV1]:
        """Unexpired artifacts called `name`, newest first: one run's, or the whole repository's."""
        path = f"/actions/runs/{run_id}/artifacts" if run_id is not None else "/actions/artifacts"
        artifacts: list[GitHubArtifactV1] = []
        page = 1
        while True:
            response = self._client.get(
                f"/repos/{self._repository}{path}", params={"name": name, "per_page": 100, "page": page}
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

    def read_single_file_artifact(self, artifact_id: int) -> bytes:
        """
        The one file in an artifact, whatever the uploader called it.

        The download redirects to blob storage; httpx drops the Authorization header when a
        redirect leaves the API origin, so the token never reaches it.
        """
        response = self._client.get(
            f"/repos/{self._repository}/actions/artifacts/{artifact_id}/zip", follow_redirects=True
        )
        response.raise_for_status()
        with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
            names = archive.namelist()
            if len(names) != 1:
                raise ValueError(f"artifact {artifact_id} holds {len(names)} files, expected one")
            return archive.read(names[0])

    def _list_comments(self, pull_request_number: int) -> list[GitHubCommentV1]:
        comments: list[GitHubCommentV1] = []
        page = 1
        while True:
            response = self._client.get(
                f"/repos/{self._repository}/issues/{pull_request_number}/comments",
                params={"per_page": 100, "page": page},
            )
            response.raise_for_status()
            batch = COMMENTS_ADAPTER.validate_json(response.content)
            comments.extend(batch)
            if len(batch) < 100:
                return comments
            page += 1

    def upsert_sticky(
        self,
        pull_request_number: int,
        marker: str,
        body: str,
        snapshot: StickySnapshotV1,
    ) -> int:
        existing = next(
            (comment for comment in self._list_comments(pull_request_number) if marker in (comment.body or "")),
            None,
        )
        if existing is not None and existing.body:
            match = SNAPSHOT_PATTERN.search(existing.body)
            if match:
                previous = StickySnapshotV1.model_validate_json(match.group("snapshot"))
                if not snapshot.supersedes(previous):
                    return existing.id
        if existing is None:
            response = self._client.post(
                f"/repos/{self._repository}/issues/{pull_request_number}/comments",
                json={"body": body},
            )
        else:
            response = self._client.patch(
                f"/repos/{self._repository}/issues/comments/{existing.id}",
                json={"body": body},
            )
        response.raise_for_status()
        return GitHubCommentV1.model_validate_json(response.content).id
