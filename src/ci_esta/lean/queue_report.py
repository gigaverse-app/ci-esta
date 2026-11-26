"""Measure required Lake jobs using GitHub Actions timestamps and runner labels."""

import argparse
import json
import statistics
import subprocess
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from math import ceil

from ci_esta.timing import iso_elapsed_seconds

WORKFLOW = "actions/workflows/build.yml/runs"
POOLS = {"rh-big", "rh-pr-fork", "rh-pr-trusted"}
CACHE = {
    "Restore Mathlib's cache",
    "Restore Tau Ceti's cache",
    "Restore this project's cache",
    "Restore prehydrated Lean dependencies",
}
PROOF = {"lake build", "Check the axioms of the five theorems"}


def phase(job, names):
    steps = [s for s in job["steps"] if s["name"] in names and s["conclusion"] != "skipped"]
    if not steps or any(not s["started_at"] or not s["completed_at"] for s in steps):
        return None
    durations = [iso_elapsed_seconds(step["started_at"], step["completed_at"]) for step in steps]
    if None in durations:
        return None
    return sum(value for value in durations if value is not None)


def summary(values):
    values = sorted(x for x in values if x is not None)
    if not values:
        return {"n": 0}
    return {
        "n": len(values),
        "median_s": statistics.median(values),
        "p95_s": values[ceil(0.95 * len(values)) - 1],
    }


def runner_pool(job):
    pools = POOLS.intersection(job["labels"])
    return next(iter(pools)) if len(pools) == 1 else "other"


def main(argv: list[str] | None = None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default="leanprover-community/riemann-hypothesis")
    parser.add_argument("--per-event", type=int, default=20, choices=range(1, 101), metavar="1-100")
    args = parser.parse_args(argv)

    def api(path):
        return json.loads(subprocess.check_output(["gh", "api", f"repos/{args.repo}/{path}"], text=True))

    def runs(event, status, limit):
        return api(f"{WORKFLOW}?event={event}&status={status}&per_page={limit}")

    def completed(run):
        path = f"actions/runs/{run['id']}/attempts/{run['run_attempt']}/jobs"
        jobs = api(path)["jobs"]
        rows = []
        for job in jobs:
            if job["name"] != "lake build" or job["conclusion"] not in {
                "success",
                "failure",
                "timed_out",
            }:
                continue
            if not job["started_at"] or not job["completed_at"]:
                continue
            rows.append(
                {
                    "run_id": run["id"],
                    "job_id": job["id"],
                    "event": run["event"],
                    "pool": runner_pool(job),
                    "conclusion": job["conclusion"],
                    "queue_s": iso_elapsed_seconds(job["created_at"], job["started_at"])
                    if job.get("created_at")
                    else None,
                    "verdict_s": iso_elapsed_seconds(run["created_at"], job["completed_at"])
                    if run["run_attempt"] == 1
                    else None,
                    "job_s": iso_elapsed_seconds(job["started_at"], job["completed_at"]),
                    "cache_s": phase(job, CACHE),
                    "proof_s": phase(job, PROOF),
                }
            )
        return rows

    def live(run):
        jobs = api(f"actions/runs/{run['id']}/jobs")["jobs"]
        return [
            {
                "run_id": run["id"],
                "job_id": job["id"],
                "pool": runner_pool(job),
                "event": run["event"],
                "status": job["status"],
                "created_at": job.get("created_at"),
                "started_at": job["started_at"] if job["status"] == "in_progress" else None,
                "active_steps": [s["name"] for s in job["steps"] if s["status"] == "in_progress"],
            }
            for job in jobs
            if job["name"] == "lake build" and job["status"] in {"queued", "in_progress"}
        ]

    with ThreadPoolExecutor(max_workers=6) as pool:
        events = ("pull_request", "merge_group", "push")
        samples = list(pool.map(lambda event: runs(event, "completed", args.per_event), events))
        queued = list(pool.map(lambda event: runs(event, "queued", args.per_event), events))
        running = list(pool.map(lambda event: runs(event, "in_progress", args.per_event), events))
        jobs = [
            row
            for batch in pool.map(completed, (r for sample in samples for r in sample["workflow_runs"]))
            for row in batch
        ]
        live_jobs = [
            row
            for batch in pool.map(
                live,
                (r for sample in queued + running for r in sample["workflow_runs"]),
            )
            for row in batch
        ]

    groups = {}
    for row in jobs:
        key = (row["event"], row["pool"])
        groups.setdefault(key, []).append(row)
    now = datetime.now(UTC).isoformat()
    live_jobs = list({row["job_id"]: row for row in live_jobs}.values())
    for row in live_jobs:
        end = row["started_at"] or now
        row["queue_s"] = iso_elapsed_seconds(row["created_at"], end) if row["created_at"] else None
    result = {
        "repository": args.repo,
        "collected_at": now,
        "cohort": "Most recent completed build workflow runs per event, up to --per-event. "
        "Job durations include failures and exclude cancellations. Queue is measured from job creation. "
        "Verdict is measured from workflow creation and excludes reruns. Missing timings are null. "
        "Live rows sample the newest queued and running workflows per event. Waiting jobs are right-censored.",
        "queued_workflows": dict(zip(events, (x["total_count"] for x in queued))),
        "sampled_completed_workflows": dict(zip(events, (len(x["workflow_runs"]) for x in samples))),
        "groups": [
            {
                "event": e,
                "pool": p,
                **{k: summary(row[k] for row in rows) for k in ("queue_s", "verdict_s", "job_s", "cache_s", "proof_s")},
            }
            for (e, p), rows in sorted(groups.items())
        ],
        "live_jobs": live_jobs,
        "jobs": jobs,
    }
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
