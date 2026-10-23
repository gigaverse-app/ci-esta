"""Keep avoided work and runner efficiency grounded in observed execution facts."""

from __future__ import annotations

from collections import Counter
from html import escape
from statistics import median
from typing import TYPE_CHECKING

from pydantic import TypeAdapter

from ci_esta.ci_observability import markdown
from ci_esta.ci_observability.enrichment.primitives import format_seconds
from ci_esta.ci_observability.enrichment.profiles import pytest_timings
from ci_esta.ci_observability.job_names import job_family
from ci_esta.measurements import (
    CacheMeasurement,
    ExecutionMeasurement,
    ImageReuseMeasurement,
    ReuseMeasurement,
    ShardPoolMeasurement,
)

if TYPE_CHECKING:
    from ci_esta.ci_observability.github import GitHubActionsClient
    from ci_esta.ci_observability.models import CiObservabilityReportV1, GitHubJobV1, GitHubRunV1

MEASUREMENT = TypeAdapter(ExecutionMeasurement)


def collect_measurements(client: GitHubActionsClient, run: GitHubRunV1, jobs: list[GitHubJobV1]):
    """One artifact listing, exact source identity, and API timings for admitted proof jobs."""
    measurements, errors = [], []
    sources = {}
    identities = set()
    try:
        artifacts = client.list_artifacts(None, run_id=run.id)
    except Exception as error:
        return [], [f"Execution measurements unavailable: {error}"]
    for artifact in artifacts:
        if not artifact.name.startswith(("ci-esta-reuse-", "ci-esta-shards-", "ci-esta-cache-", "ci-esta-image-")):
            continue
        try:
            if not artifact.from_same_repository or artifact.workflow_run.id != run.id:
                raise ValueError("measurement artifact is not from this repository run")
            item = MEASUREMENT.validate_json(client.read_single_file_artifact(artifact.id))
            if (item.run_id, item.run_attempt, item.head_sha) != (run.id, run.run_attempt, run.head_sha):
                # A run's artifact listing includes earlier attempts. They are not current evidence.
                continue
            if isinstance(item, ReuseMeasurement):
                lanes = []
                for lane in item.lanes:
                    current = [job for job in jobs if job_family(job.name) == job_family(lane.job)]
                    if not current or any(job.conclusion != "skipped" for job in current):
                        continue
                    try:
                        key = (lane.source_run_id, lane.source_attempt)
                        if key not in sources:
                            source = client.get_run(key[0], run_attempt=key[1])
                            source_jobs = client.list_jobs(key[0], include_all_attempts=False, run_attempt=key[1])
                            sources[key] = (source, source_jobs)
                        source, source_jobs = sources[key]
                        proof = next((job for job in source_jobs if job.id == lane.source_job_id), None)
                        if (source.id != lane.source_run_id or source.head_sha != lane.source_head_sha
                            or source.run_attempt != lane.source_attempt or run.workflow_id is None
                            or source.workflow_id != run.workflow_id or source.id == run.id
                            or proof is None or proof.run_attempt != lane.source_attempt
                            or proof.name != lane.job or proof.conclusion != "success"):
                            raise ValueError("reuse source job does not match admitted evidence")
                        seconds = None
                        if proof.started_at is not None and proof.completed_at is not None:
                            seconds = (proof.completed_at - proof.started_at).total_seconds()
                            if seconds < 0:
                                seconds = None
                        identity = ("reuse", proof.id)
                        if identity not in identities:
                            identities.add(identity)
                            lanes.append(lane.model_copy(update={"source_seconds": seconds}))
                    except Exception as error:
                        errors.append(f"{artifact.name} / {lane.lane}: {error}")
                measurements.append(item.model_copy(update={"lanes": lanes}))
            elif isinstance(item, ShardPoolMeasurement):
                identity = ("pool", item.pool)
                if identity in identities:
                    raise ValueError("duplicate shard pool measurement")
                identities.add(identity)
                measurements.append(item)
            else:
                identity = (item.schema_version, item.job, item.scope)
                if identity in identities:
                    raise ValueError("duplicate action measurement")
                identities.add(identity)
                measurements.append(item)
        except Exception as error:
            errors.append(f"{artifact.name}: {error}")
    return measurements, errors


def reused_lanes(report: CiObservabilityReportV1):
    return [lane for item in report.measurements if isinstance(item, ReuseMeasurement) for lane in item.lanes]


def reused_lane_count(report: CiObservabilityReportV1) -> int:
    return len({(lane.lane, job_family(lane.job)) for lane in reused_lanes(report)})


def _details(summary: str, body: list[str]) -> str:
    return "\n".join([f"<details><summary>{summary}</summary>", "", *body, "", "</details>", ""])


def render_avoided_work(report: CiObservabilityReportV1) -> str:
    lanes = reused_lanes(report)
    lane_count = reused_lane_count(report)
    caches = [item for item in report.measurements if isinstance(item, CacheMeasurement)]
    counts = Counter(item.outcome for item in caches)
    known_reuse = any(isinstance(item, ReuseMeasurement) for item in report.measurements)
    summary = [f"{lane_count} proven lane{'s' if lane_count != 1 else ''} reused" if known_reuse else "reuse unmeasured"]
    timed = [lane.source_seconds for lane in lanes if lane.source_seconds is not None]
    if timed:
        summary.append(f"≈{format_seconds(sum(timed))} runner time avoided")
    lookups = sum(counts[key] for key in ("hit", "miss", "repaired"))
    summary.append(f"{counts['hit']}/{lookups} environment cache hits" if lookups else "no measured cache lookups")
    body = ["#### Reused validation evidence", ""]
    if lanes:
        body += ["| Lane | Successful source | Source job duration |", "|:--|:--|--:|"]
        for lane in lanes:
            url = (f"https://github.com/{report.provenance.repository}/actions/runs/{lane.source_run_id}"
                   f"/job/{lane.source_job_id}")
            duration = format_seconds(lane.source_seconds) if lane.source_seconds is not None else "unavailable"
            body.append(f"| {markdown.cell(markdown.code(lane.lane))} | "
                        f"[{markdown.cell(markdown.code(lane.job))}, attempt {lane.source_attempt}]({url}) | {duration} |")
        body += ["", "Avoided runner time estimates the durations of the original successful jobs. "
                 "It is not a new execution measurement, a wall-clock saving, or billed minutes. "
                 "Only jobs skipped in this attempt are counted; missing source durations remain unknown.", ""]
    else:
        body += ["No receipt-proven reuse in this attempt." if known_reuse else
                 "Reuse evidence was not recorded. Skipped jobs alone do not prove reuse.", ""]
    for item in report.measurements:
        if isinstance(item, ReuseMeasurement) and item.lanes:
            body += [f"Receipt: {markdown.code(item.receipt)}.",
                     f"Execution context: {markdown.code(item.execution_context or 'default')}.", ""]
    body += ["#### Environment caching", ""]
    if caches:
        body += ["| Job | Observed outcome after locked sync | Validation / sync |", "|:--|:--|--:|",
                 *(f"| {markdown.cell(markdown.code(item.job))} | {item.outcome} | {format_seconds(item.sync_seconds)} |"
                   for item in caches), "",
                 "Every recorded environment passed locked synchronization. A restored but unusable environment "
                 "is recorded as repaired. Download caches are separate and are not included in these counts.", ""]
    else:
        body += ["No validated environment cache outcomes were recorded.", ""]
    body += ["Cache time saved is unavailable without a comparable cold run."]
    images = [item for item in report.measurements if isinstance(item, ImageReuseMeasurement)]
    if images:
        summary.append(f"{len(images)} verified image reuses")
        body += ["", "#### Image reuse", "", "| Job | Verified image digest |", "|:--|:--|",
                 *(f"| {markdown.cell(markdown.code(item.job))} | {markdown.code(item.digest)} |" for item in images),
                 "", "The source and target image digests matched. Build time avoided is unknown without a comparable build; "
                 "image promotions are not added to lane-reuse totals."]
    cache_signals = [signal for signal in report.repository_signals if signal.key == "mean_docker_cache_hit"]
    body += ["", *(f"{markdown.inline(signal.label)}: {markdown.inline(signal.value)}." for signal in cache_signals)]
    body += ["", "Incremental test evidence is not inferred from skipped jobs or added to whole-lane reuse totals."]
    if report.measurement_errors:
        body += ["", "Measurement gaps:", *(f"- {markdown.inline(error)}" for error in report.measurement_errors)]
    return _details("♻️ What else avoided work? · " + escape(" · ".join(summary)), body)


def render_sharding(report: CiObservabilityReportV1) -> str:
    pools = [item for item in report.measurements if isinstance(item, ShardPoolMeasurement)]
    timings = pytest_timings(report.extensions)
    if timings is None and report.test_selection is not None and not isinstance(report.test_selection, dict):
        timings = report.test_selection.pytest
    signals = [signal for signal in report.repository_signals if signal.key == "pytest_parallelism"]
    summary, body = [], []
    if pools:
        indices = [shard.index for pool in pools for shard in pool.shards]
        configured = {pool.configured_shards for pool in pools}
        complete = len(configured) == 1 and sorted(indices) == list(range(1, next(iter(configured)) + 1))
        capacity = sum(pool.capacity_seconds for pool in pools)
        active = sum(pool.active_seconds for pool in pools)
        summary += [f"{len(indices)} measured shards / {len(pools)} pool{'s' if len(pools) != 1 else ''}"]
        if complete and capacity > 0:
            summary += [f"{active / capacity:.0%} slot occupancy"]
        else:
            summary += ["overall occupancy unavailable (incomplete or overlapping pools)"]
        body += ["| Pool | Slots | Visible logical CPUs | Observed wall | Slot occupancy | Idle slot-time | Tail / median |",
                 "|:--|--:|--:|--:|--:|--:|--:|"]
        for pool in pools:
            durations = [shard.seconds for shard in pool.shards]
            middle = median(durations)
            balance = f"{max(durations) / middle:.2f}×" if middle else "unavailable"
            occupancy = f"{pool.active_seconds / pool.capacity_seconds:.0%}" if pool.capacity_seconds else "unavailable"
            idle = format_seconds(max(0, pool.capacity_seconds - pool.active_seconds))
            body += [f"| {markdown.cell(markdown.code(pool.pool))} | {len(pool.shards)} | {pool.cpu_count or 'unknown'} | "
                     f"{format_seconds(pool.wall_seconds)} | {occupancy} | {idle} idle slot-time | {balance} |"]
        body += ["", "Slot occupancy = observed child-process time / (allocated shard slots × pool wall time). "
                 "It includes test startup and subprocess waits; it is not CPU utilization. "
                 "Pool clocks are independent, so pool wall times are not summed into a workflow duration. "
                 "Exit detection is polled (normally every 0.1s); timestamps are observation bounds.", "",
                 "| Pool / shard | Start offset | End offset | Duration | Exit code |", "|:--|--:|--:|--:|--:|"]
        for pool in pools:
            for shard in pool.shards:
                body.append(f"| {markdown.cell(markdown.code(pool.pool))} / {shard.index} | {shard.start_seconds:.2f}s | "
                            f"{shard.end_seconds:.2f}s | {shard.seconds:.2f}s | {shard.exit_code} |")
    else:
        summary += [f"{timings.shard_count} shards" if timings else "shards unmeasured", "occupancy unavailable"]
        body += ["Process intervals were not recorded. Aggregate JUnit durations cannot establish pool occupancy."]
    if timings:
        wall = format_seconds(timings.wall_seconds) if timings.wall_seconds is not None else "unknown"
        total = format_seconds(timings.total_test_seconds) if timings.total_test_seconds is not None else "unknown"
        body += ["", f"Reported pytest timings: {timings.shard_count} shards, {wall} longest-shard wall, "
                 f"{total} summed test time. JUnit durations omit work outside its timed suites."]
    body += ["", *(f"{markdown.inline(signal.label)}: {markdown.inline(signal.value)}." for signal in signals),
             "CPU quota, throttling and predicted-duration error are unavailable unless separately measured."]
    return _details("⚡ Sharding &amp; runner efficiency · " + escape(" · ".join(summary)), body)
