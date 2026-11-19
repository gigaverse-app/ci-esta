"""CPU capacity occupied by completed jobs on one-pod-per-job Kubernetes runners."""
import json
import math
from concurrent.futures import ThreadPoolExecutor
from itertools import pairwise

import httpx
from pydantic import BaseModel

from ci_esta.ci_observability import markdown
from ci_esta.ci_observability.models import ObservedJobV1, RunnerCpuAllocation, RunnerSkuRateV1
from ci_esta.ci_observability.pricing import STANDARD_LABEL_SKUS, standard_cores


class CounterSeries(BaseModel):
    values: list[tuple[float, float]]


class QueryData(BaseModel):
    result: list[CounterSeries]


class QueryResponse(BaseModel):
    data: QueryData


def measure(counter: CounterSeries, start: float, end: float, allocation: RunnerCpuAllocation) -> None:
    """Interpolate only between consecutive usable scrapes. Never extrapolate."""
    for (t0, v0), (t1, v1) in pairwise(counter.values):
        overlap = min(t1, end) - max(t0, start)
        if overlap <= 0 or not 0 < t1 - t0 <= 75 or not 0 <= v0 <= v1 or not math.isfinite(v1):
            continue
        cores = (v1 - v0) / (t1 - t0)
        allocation.covered_seconds += overlap
        allocation.used_core_seconds = (allocation.used_core_seconds or 0) + cores * overlap
        allocation.peak_sampled_cores = max(cores, allocation.peak_sampled_cores or 0)


def collect(jobs: list[ObservedJobV1], rates: list[RunnerSkuRateV1], url: str | None, namespace: str,
            *, repository_private: bool | None = None) -> list[ObservedJobV1]:
    catalog = {r.runner_label: r for r in rates}
    with httpx.Client(timeout=5, trust_env=False) as client:
        def read(job: ObservedJobV1) -> ObservedJobV1:
            labels = catalog.keys() & job.runner_labels
            if (len(labels) > 1 or not job.runner_name or not job.started_at or not job.completed_at
                    or not job.wall_seconds or job.status != "completed" or job.conclusion == "skipped"):
                return job
            label = next(iter(labels), job.runner_labels[0] if len(job.runner_labels) == 1 else "")
            rate = catalog.get(label)
            cores = rate.allocated_cores if rate else None
            standard_hosted = len(job.runner_labels) == 1 and job.runner_group_name in (None, "GitHub Actions")
            if cores is None and standard_hosted and (not rate or rate.sku == STANDARD_LABEL_SKUS.get(label)):
                cores = standard_cores(label, repository_private)
            if cores is None:
                return job
            allocation = RunnerCpuAllocation(pool=label, cores=cores, occupied_seconds=job.wall_seconds)
            allocated_job = job.model_copy(update={"cpu_allocation": allocation})
            if not url or not rate or rate.allocated_cores is None or job.runner_group_name == "GitHub Actions":
                return allocated_job
            start, end = job.started_at.timestamp(), job.completed_at.timestamp()
            # The pod cgroup includes the runner, Docker daemon and child containers exactly once.
            selector = ('container_cpu_usage_seconds_total{container="",cpu="total",id=~".*pod[^/]+[.]slice",'
                        f'namespace={json.dumps(namespace)},pod={json.dumps(job.runner_name)}}}')
            try:
                response = client.get(url.rstrip("/") + "/api/v1/query", params={
                    "query": f"{selector}[{math.ceil(end-start)+151}s]", "time": end + 75})
                response.raise_for_status()
                series = QueryResponse.model_validate_json(response.content).data.result
                if len(series) == 1:
                    measure(series[0], start, end, allocation)
            except (httpx.HTTPError, ValueError):
                # Resource observations are optional and independent per job.
                pass
            return allocated_job

        with ThreadPoolExecutor(max_workers=6) as executor:
            return list(executor.map(read, jobs))


def section(jobs: list[ObservedJobV1]) -> list[str]:
    rows = [(j, j.cpu_allocation) for j in jobs if j.cpu_allocation]
    if not rows:
        return []
    rows.sort(key=lambda pair: (pair[1].used_core_seconds is not None, pair[1].unused_core_seconds or 0), reverse=True)
    total = sum(a.allocated_core_seconds for _, a in rows)
    covered = sum(a.covered_seconds * a.cores for _, a in rows)
    unused = sum(a.unused_core_seconds for _, a in rows if a.unused_core_seconds is not None)
    details = ["Unused = covered reservation minus pod CPU time. Bursts above reservation appear as negative values. "
               "Peak is the fastest sampled interval. Missing intervals are excluded.", "",
               "| Job (attempt) | Pool | Reserved cores | Coverage | Used / unused core-s | Peak cores | Queue |",
               "|---|---|---:|---:|---:|---:|---:|"]
    for j, a in rows[:15]:
        usage = f"{a.used_core_seconds:.0f} / {a.unused_core_seconds:.0f}" if a.covered_seconds else "unknown"
        peak = f"{a.peak_sampled_cores:.1f}" if a.peak_sampled_cores is not None else "unknown"
        queue = f"{j.queue_seconds:.0f} s" if j.queue_seconds is not None else "unknown"
        details.append(f"| {markdown.cell(j.name)} ({j.run_attempt}) | {markdown.cell(a.pool)} | {a.cores:g} | "
                       f"{a.covered_seconds/a.occupied_seconds:.0%} | {usage} | {peak} | {queue} |")
    headline = (f"{unused:,.0f} unused core-s over {covered:,.0f} measured core-s" if covered else "CPU usage unavailable")
    return [markdown.report_section("Runner CPU allocation", [headline, f"{covered/total:.0%} coverage of "
                                    f"{total:,.0f} reserved core-s across {len(rows)} jobs"], details)]


def metrics(jobs: list[ObservedJobV1]) -> list[str]:
    pools: dict[str, list[RunnerCpuAllocation]] = {}
    for job in jobs:
        if job.cpu_allocation:
            pools.setdefault(job.cpu_allocation.pool, []).append(job.cpu_allocation)
    lines = []
    for pool, rows in sorted(pools.items()):
        covered = sum(a.covered_seconds * a.cores for a in rows)
        values = {"allocated": sum(a.allocated_core_seconds for a in rows), "covered": covered}
        if covered:
            values.update(used=sum(a.used_core_seconds for a in rows if a.used_core_seconds is not None), unused=sum(a.unused_core_seconds for a in rows if a.unused_core_seconds is not None))
        for name, value in values.items():
            lines.append(f'ci_runner_cpu_{name}_core_seconds{{pool={json.dumps(pool)}}} {value:g}')
    return lines

