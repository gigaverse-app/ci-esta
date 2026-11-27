"""Measure how long one GitHub Actions job waits for a runner, restores caches and works, per runner pool."""

import argparse
import json
import statistics
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from math import ceil

from ci_esta.pagination import collect_pages
from ci_esta.timing import iso_elapsed_seconds

EVENTS = ("pull_request", "merge_group", "push")
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


def runner_pool(job, pools=POOLS):
    """The one named pool among the job's runner labels; with no pools named, the labels themselves."""
    if not pools:
        return ",".join(sorted(job["labels"])) or "other"
    matched = set(pools).intersection(job["labels"])
    return next(iter(matched)) if len(matched) == 1 else "other"


def main(argv: list[str] | None = None, *, lean: bool = True):
    """`lean` supplies the Riemann Hypothesis project's workflow, job, steps and pools as defaults."""
    parser = argparse.ArgumentParser(prog="ci-esta-lean queue" if lean else "ci-esta queue", description=__doc__)
    parser.add_argument("--repo", required=not lean, default="leanprover-community/riemann-hypothesis" if lean else None,
                        help="OWNER/NAME on GitHub")
    parser.add_argument("--workflow", required=not lean, default="build.yml" if lean else None,
                        help="Workflow file name, such as ci.yml")
    parser.add_argument("--job", required=not lean, default="lake build" if lean else None,
                        help="Exact name of the job to measure")
    parser.add_argument("--cache-step", action="append", metavar="NAME",
                        help="A step that restores a cache; repeat for each. Their time is cache_s")
    parser.add_argument("--work-step", action="append", metavar="NAME",
                        help="A step that does the job's real work; repeat for each. Their time is work_s")
    parser.add_argument("--pool", action="append", metavar="LABEL",
                        help="A runner label that names a pool; repeat for each. Default: group by all labels")
    parser.add_argument("--event", action="append", metavar="NAME",
                        help="An event that starts the workflow, such as schedule or workflow_dispatch; "
                        f"repeat for each. Default: {', '.join(EVENTS)}")
    parser.add_argument("--per-event", type=int, default=20, choices=range(1, 101), metavar="1-100")
    args = parser.parse_args(argv)
    try:
        report(args, lean)
    except subprocess.CalledProcessError as error:
        # `gh` has already written GitHub's answer, such as `Not Found (HTTP 404)`, to standard error.
        print(f"{parser.prog}: {' '.join(error.cmd)} failed; check --repo and --workflow", file=sys.stderr)
        raise SystemExit(1) from None


def report(args: argparse.Namespace, lean: bool) -> None:
    workflow = f"actions/workflows/{args.workflow}/runs"
    cache = set(args.cache_step or (CACHE if lean else ()))
    work = set(args.work_step or (PROOF if lean else ()))
    pools = set(args.pool or (POOLS if lean else ()))
    work_key = "proof_s" if lean else "work_s"

    def api(path):
        return json.loads(subprocess.check_output(["gh", "api", f"repos/{args.repo}/{path}"], text=True))

    def all_jobs(path):
        """Every job of a run: GitHub returns at most 100 per page, and a large matrix has more."""
        jobs = collect_pages(
            lambda page: api(f"{path}?per_page=100" + (f"&page={page}" if page > 1 else ""))["jobs"]
        )
        seen.update(job["name"] for job in jobs)
        return jobs

    def runs(event, status, limit):
        return api(f"{workflow}?event={event}&status={status}&per_page={limit}")

    def completed(run):
        jobs = all_jobs(f"actions/runs/{run['id']}/attempts/{run['run_attempt']}/jobs")
        rows = []
        for job in jobs:
            if job["name"] != args.job or job["conclusion"] not in {
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
                    "pool": runner_pool(job, pools),
                    "conclusion": job["conclusion"],
                    "queue_s": iso_elapsed_seconds(job["created_at"], job["started_at"])
                    if job.get("created_at")
                    else None,
                    "verdict_s": iso_elapsed_seconds(run["created_at"], job["completed_at"])
                    if run["run_attempt"] == 1
                    else None,
                    "job_s": iso_elapsed_seconds(job["started_at"], job["completed_at"]),
                    "cache_s": phase(job, cache),
                    work_key: phase(job, work),
                }
            )
        return rows

    def live(run):
        jobs = all_jobs(f"actions/runs/{run['id']}/jobs")
        return [
            {
                "run_id": run["id"],
                "job_id": job["id"],
                "pool": runner_pool(job, pools),
                "event": run["event"],
                "status": job["status"],
                "created_at": job.get("created_at"),
                "started_at": job["started_at"] if job["status"] == "in_progress" else None,
                "active_steps": [s["name"] for s in job["steps"] if s["status"] == "in_progress"],
            }
            for job in jobs
            if job["name"] == args.job and job["status"] in {"queued", "in_progress"}
        ]

    seen: set[str] = set()
    events = tuple(dict.fromkeys(args.event or EVENTS))
    with ThreadPoolExecutor(max_workers=6) as pool:
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
        "workflow": args.workflow,
        "job": args.job,
        "cohort": "Most recent completed workflow runs per event, up to --per-event. "
        "Job durations include failures and exclude cancellations. Queue is measured from job creation. "
        "Verdict is measured from workflow creation and excludes reruns. Missing timings are null. "
        "Live rows sample the newest queued and running workflows per event. Waiting jobs are right-censored.",
        "queued_workflows": dict(zip(events, (x["total_count"] for x in queued))),
        "sampled_completed_workflows": dict(zip(events, (len(x["workflow_runs"]) for x in samples))),
        "groups": [
            {
                "event": e,
                "pool": p,
                **{k: summary(row[k] for row in rows) for k in ("queue_s", "verdict_s", "job_s", "cache_s", work_key)},
            }
            for (e, p), rows in sorted(groups.items())
        ],
        "live_jobs": live_jobs,
        "jobs": jobs,
    }
    print(json.dumps(result, indent=2))
    if not jobs and not live_jobs:
        prog = "ci-esta-lean queue" if lean else "ci-esta queue"
        if seen:
            print(f"{prog}: no job named {args.job!r} in the sampled runs; their jobs: "
                  f"{', '.join(sorted(seen))}", file=sys.stderr)
        else:
            print(f"{prog}: {args.workflow} has no runs started by {', '.join(events)}; "
                  "name the events that start it with --event", file=sys.stderr)


if __name__ == "__main__":
    main()
