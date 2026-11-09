"""Best-effort GitHub access for backend-only log enrichment."""

from __future__ import annotations

import os
import re
from functools import partial

import httpx
from pydantic import TypeAdapter

from ci_esta.ci_observability.enrichment.backend.models import (
    GitHubComment,
    GitHubEnrichment,
    GitHubJob,
    InfraSignal,
)
from ci_esta.ci_observability.github import GitHubActionsClient

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


class GitHubClient(GitHubActionsClient):
    """Backend's legacy-sticky migration on the shared API client."""
    def mark_legacy_sticky(self, pull_request: int, comment: GitHubComment) -> None:
        self.update_comment(comment.id, f"{comment.body or ''}\n{SHARED_STICKY_MARKER}")


github_client = partial(GitHubClient.from_environment, required=False)


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
