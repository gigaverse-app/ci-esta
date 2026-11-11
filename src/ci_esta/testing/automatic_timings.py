"""Discover merged observations during the existing timing restore operation.

This is advisory read-time learning, not a trusted-checkpoint writer. Each source
still passes the canonical latest-attempt collector before reaching shared hints.
"""

from __future__ import annotations

from pathlib import PurePosixPath
from zipfile import BadZipFile

import httpx

from ci_esta.ci_observability.github import GitHubActionsClient
from ci_esta.testing.merged_pr_timings import (
    MergedPRTimingCollector,
    PromotionDecision,
    PromotionPolicy,
    automatic_name,
    publish_promotion,
)
from ci_esta.testing.timing_store import TimingHistory


def stage_automatic(client: GitHubActionsClient, key: str, branch: str,
                    number: int, run_id: int) -> PromotionDecision:
    candidate = client.get_run(run_id)
    if candidate.event != "pull_request" or candidate.path is None:
        return PromotionDecision(status="rejected", reason="automatic candidate is not a PR producer")
    policy = PromotionPolicy(repository=client.repository, branch=branch,
                             workflow=PurePosixPath(candidate.path).name, key=key, automatic=True)
    collector = MergedPRTimingCollector(client, policy)
    # Discovery may encounter an older artifact first. The canonical collector
    # always selects the latest attempt itself; it never trusts discovery order.
    return collector.stage(number)


def learn_merged_observations(client: GitHubActionsClient, state: TimingHistory,
                              branch: str, max_sources: int) -> TimingHistory:
    """Bound discovery work; missed old observations retain the existing baseline.

    Discovery covers the latest 300 repository artifacts. It is not an inventory
    assertion: every discovered run independently receives complete admission
    checks, including enumeration of all newer attempts on its final PR head.
    """
    seen: set[int] = set()
    considered: set[tuple[int, str | None]] = set()
    for artifact in client.list_artifacts(None, recent_pages=3):
        if (not artifact.name.startswith(automatic_name(state.key))
                or not artifact.from_same_repository or artifact.workflow_run is None):
            continue
        run_id = artifact.workflow_run.id
        if run_id in seen:
            continue
        if len(seen) >= max_sources:
            break
        seen.add(run_id)
        if any(run_id == imported.run_id for imported in state.imports.values()):
            continue
        try:
            candidate = client.get_run(run_id)
            for pr in client.pulls_for_commit(candidate.head_sha):
                identity = (pr.number, candidate.path)
                if identity in considered:
                    continue
                considered.add(identity)
                decision = stage_automatic(client, state.key, branch, pr.number, run_id)
                if decision.promotion is not None:
                    state = publish_promotion(state, decision.promotion)
        except (ValueError, OSError, BadZipFile, httpx.HTTPError) as error:
            print(f"::warning::Merged timing source {run_id} unavailable ({type(error).__name__}); retaining history")
    return state
