"""Trusted-branch collector entrypoint. No checkout or execution of PR code."""

from __future__ import annotations

import json
import os
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zipfile import BadZipFile

import httpx

from ci_esta.git import git
from ci_esta.testing.merged_pr_timings import MergedPRTimingCollector, PromotionPolicy, publish_promotion
from ci_esta.testing.timing_artifacts import action_histories, artifact_name, github_client, history_branch
from ci_esta.testing.timing_store import combine_histories, observation_stamp, tracked_python_files, write_history


def main() -> None:
    client = github_client()
    try:
        branch = history_branch()
        run = client.get_run(int(os.environ["GITHUB_RUN_ID"]),
                             run_attempt=int(os.environ.get("GITHUB_RUN_ATTEMPT", "1")))
        if (run.event not in {"push", "schedule", "workflow_dispatch"} or run.head_branch != branch
                or os.environ.get("GITHUB_REF") != f"refs/heads/{branch}"):
            raise ValueError("timing promotion requires a trusted-branch push, schedule or dispatch collector")
        if git(Path("."), "rev-parse", "HEAD").strip() != run.head_sha:
            raise ValueError("collector checkout does not match its trusted run revision")
        policy = PromotionPolicy(
            repository=os.environ["GITHUB_REPOSITORY"], branch=branch,
            workflow=os.environ["INPUT_PRODUCER_WORKFLOW"], key=os.environ["INPUT_HISTORY_KEY"],
            gates=json.loads(os.environ["INPUT_REQUIRED_GATES"]),
            shards=json.loads(os.environ.get("INPUT_EXPECTED_SHARDS", '{"all":1}')),
        )
        now = datetime.now(timezone.utc)
        state = combine_histories(action_histories(client, policy.key), policy.key, now)
        if number := int(os.environ.get("INPUT_PULL_REQUEST", "0")):
            numbers = [number]
        elif source_id := int(os.environ.get("INPUT_SOURCE_RUN", "0")):
            source = client.get_run(source_id)
            candidates = [client.pull_request(pr.number) for pr in client.pulls_for_commit(source.head_sha)]
            numbers = [pr.number for pr in candidates if pr.merged_at is not None and pr.head.sha == source.head_sha]
        elif run.event == "push":
            candidates = [client.pull_request(pr.number) for pr in client.pulls_for_commit(run.head_sha)]
            numbers = [pr.number for pr in candidates if pr.merge_commit_sha == run.head_sha]
        else:
            days = int(os.environ.get("INPUT_LOOKBACK_DAYS", "7"))
            if not 1 <= days <= 21:
                raise ValueError("lookback-days must be between 1 and the 21-day measurement retention")
            since = now - timedelta(days=days)
            candidates = [pr for pr in client.recent_closed_pulls(since)
                          if pr.merged_at is not None and pr.merged_at >= since and pr.base.ref == branch]
            # Successful imports are immutable. Skip their API/artifact downloads
            # during recurring catch-up; retry only pending/new merged sources.
            numbers = [pr.number for pr in candidates if not any(
                identity.startswith(f"{policy.repository}/") and imported.pull_request == pr.number
                and imported.head_sha == pr.head.sha and imported.merge_commit_sha == pr.merge_commit_sha
                and imported.workflow == f".github/workflows/{policy.workflow}"
                for identity, imported in state.imports.items()
            )]
        collector = MergedPRTimingCollector(client, policy)
        counts: Counter[str] = Counter()
        for number in numbers:
            try:
                decision = collector.stage(number)
                if decision.promotion is not None:
                    already = decision.promotion.identity in state.imports
                    state = publish_promotion(state, decision.promotion)
                    counts["already imported" if already else "imported"] += 1
                else:
                    counts[decision.status] += 1
                print(f"PR #{number}: {decision.status}: {decision.reason}")
            except (ValueError, OSError, BadZipFile, httpx.HTTPError) as error:
                counts["unavailable"] += 1
                # Do not leak API credentials or artifact contents in diagnostics.
                print(f"::warning::PR #{number}: evidence unavailable ({type(error).__name__}); retry on next collection")
        publish = counts["imported"] > 0
        if publish:
            # The inventory is current main; observations retain their PR source stamps.
            stamp = observation_stamp(run.created_at, run.id, run.run_attempt)
            if stamp > state.inventory_stamp:
                state.inventory_stamp = stamp
                state.inventory_at = run.created_at
                state.tracked_files = tracked_python_files(Path("."))
            state.producer_run_id = run.id
            state.producer_attempt = run.run_attempt
            state.expire(now)
            path = Path(os.environ["RUNNER_TEMP"]) / f"{artifact_name(policy.key)}-{run.id}-{run.run_attempt}.json"
            write_history(state, path)
            with Path(os.environ["GITHUB_OUTPUT"]).open("a") as stream:
                stream.write(f"history-path={path}\nhistory-name={artifact_name(policy.key)}\npublish=true\n")
        summary = f"Merged PR timing collection: {dict(counts)}. Scheduling hints only; no test receipts issued.\n"
        print(summary)
        if destination := os.environ.get("GITHUB_STEP_SUMMARY"):
            with Path(destination).open("a", encoding="utf-8") as stream:
                stream.write(summary)
    finally:
        client.close()


if __name__ == "__main__":
    main()
