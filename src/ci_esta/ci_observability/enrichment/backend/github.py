"""Best-effort GitHub access for backend-only log enrichment."""

from __future__ import annotations

import os
import re

import httpx
from pydantic import TypeAdapter

from ci_esta.ci_observability.enrichment.backend.models import (
    GitHubComment,
    GitHubEnrichment,
    GitHubJob,
    GitHubJobsPage,
    InfraSignal,
)

LEGACY_STICKY_MARKER = "<!-- ci-cost-report -->"
SHARED_STICKY_MARKER = "<!-- ci-observability-v1 -->"

COMMENTS_ADAPTER = TypeAdapter(list[GitHubComment])

INFRA_SIGNATURES = (
    (re.compile(r"No space left on device"), "shared storage full"),
    (re.compile(r"ImagePullBackOff|ErrImagePull"), "image pull failed"),
    (re.compile(r"OOMKilled"), "pod OOMKilled"),
)
TIMESTAMP_PREFIX = re.compile(r"^\S+Z\s+")


def detect_infra(log: str) -> list[InfraSignal]:
    found: dict[str, str] = {}
    for line in log.splitlines():
        for pattern, label in INFRA_SIGNATURES:
            if label not in found and pattern.search(line):
                found[label] = TIMESTAMP_PREFIX.sub("", line).strip()[:200]
    return [InfraSignal(label=label, line=line) for label, line in found.items()]


class GitHubClient:
    def __init__(
        self,
        repository: str,
        token: str,
        api_url: str,
        *,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.repository = repository
        self.client = httpx.Client(
            base_url=api_url,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            follow_redirects=True,
            timeout=20,
            transport=transport,
        )

    def close(self) -> None:
        self.client.close()

    def list_jobs(self, run_id: str) -> list[GitHubJob]:
        jobs: list[GitHubJob] = []
        page = 1
        while True:
            response = self.client.get(
                f"/repos/{self.repository}/actions/runs/{run_id}/jobs",
                params={"filter": "latest", "per_page": 100, "page": page},
            )
            response.raise_for_status()
            chunk = GitHubJobsPage.model_validate(response.json()).jobs
            jobs.extend(chunk)
            if len(chunk) < 100:
                return jobs
            page += 1

    def job_log(self, job_id: int) -> str:
        response = self.client.get(f"/repos/{self.repository}/actions/jobs/{job_id}/logs")
        response.raise_for_status()
        return response.text

    def list_comments(self, pull_request: int) -> list[GitHubComment]:
        comments: list[GitHubComment] = []
        page = 1
        while True:
            response = self.client.get(
                f"/repos/{self.repository}/issues/{pull_request}/comments",
                params={"per_page": 100, "page": page},
            )
            response.raise_for_status()
            chunk = COMMENTS_ADAPTER.validate_python(response.json())
            comments.extend(chunk)
            if len(chunk) < 100:
                return comments
            page += 1

    def mark_legacy_sticky(self, pull_request: int, comment: GitHubComment) -> None:
        response = self.client.patch(
            f"/repos/{self.repository}/issues/comments/{comment.id}",
            json={"body": f"{comment.body or ''}\n{SHARED_STICKY_MARKER}"},
        )
        response.raise_for_status()


def github_client() -> GitHubClient | None:
    repository = os.environ.get("GITHUB_REPOSITORY", "")
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN", "")
    if not repository or not token:
        return None
    return GitHubClient(
        repository,
        token,
        os.environ.get("GITHUB_API_URL", "https://api.github.com"),
    )


def collect_github_enrichment() -> GitHubEnrichment:
    client = github_client()
    run_id = os.environ.get("GITHUB_RUN_ID")
    if client is None or not run_id:
        return GitHubEnrichment()

    unavailable: list[str] = []
    infra_by_label: dict[str, InfraSignal] = {}
    jobs: list[GitHubJob] = []
    try:
        jobs = client.list_jobs(run_id)
        for job in jobs:
            if job.conclusion == "skipped":
                continue
            if job.conclusion not in {
                "failure",
                "cancelled",
                "timed_out",
            }:
                continue
            try:
                log = client.job_log(job.id)
            except httpx.HTTPError as error:
                unavailable.append(f"log unavailable for {job.name}: {error}")
                continue
            for signal in detect_infra(log):
                infra_by_label.setdefault(signal.label, signal)
    except httpx.HTTPError as error:
        unavailable.append(f"backend GitHub enrichment unavailable: {error}")
    finally:
        client.close()
    return GitHubEnrichment(
        infra_signals=list(infra_by_label.values()),
        unavailable=unavailable,
    )


def adopt_legacy_sticky(pull_request: int) -> None:
    client = github_client()
    if client is None:
        return
    try:
        comments = client.list_comments(pull_request)
        if any(SHARED_STICKY_MARKER in (comment.body or "") for comment in comments):
            return
        legacy = next(
            (comment for comment in comments if LEGACY_STICKY_MARKER in (comment.body or "")),
            None,
        )
        if legacy:
            client.mark_legacy_sticky(pull_request, legacy)
    finally:
        client.close()
