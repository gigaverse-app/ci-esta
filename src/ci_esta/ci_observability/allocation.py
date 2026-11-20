"""CPU reservations and measured counter intervals for completed CI jobs."""
import json
import math
import re
from collections.abc import Callable, Iterator, Set
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from itertools import pairwise

import httpx
from pydantic import BaseModel

from ci_esta.ci_observability import markdown
from ci_esta.ci_observability.models import ObservedJobV1, RunnerCpuAllocation, RunnerSkuRateV1
from ci_esta.ci_observability.pricing import GITHUB_SKU_PRICES, STANDARD_LABEL_SKUS, standard_cores


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


RESOURCE_LINE = re.compile(
    r"^(\d{4}-\d{2}-\d{2}T[\d:.]+Z) \[ci-test-resource\] "
    r"(?:(initial cpu\.stat|final cpu\.stat)$|(?:  |cpu\.stat )usage_usec (\d+)(?: .*)?$)", re.MULTILINE,
)


def resource_counters(log: str) -> Iterator[CounterSeries]:
    """Read each invocation of ci-esta-resources separately, including cancelled commands."""
    samples: list[tuple[float, float]] = []
    active = final = False
    for match in RESOURCE_LINE.finditer(log.replace("\r\n", "\n")):
        marker = match[2]
        if marker == "initial cpu.stat":
            if samples:
                yield CounterSeries(values=samples)
            samples = []
            active, final = True, False
        elif active and marker == "final cpu.stat":
            final = True
        elif active and match[3] is not None:
            time = datetime.fromisoformat(match[1]).timestamp()
            # Startup prints two reads in milliseconds. Log delivery is too
            # coarse to interpret such pairs as peaks in CPU usage.
            if not samples or time - samples[-1][0] >= 1:
                samples.append((time, int(match[3]) / 1_000_000))
            if final:
                yield CounterSeries(values=samples)
                samples = []
                active = final = False
    if samples:
        yield CounterSeries(values=samples)


JOB_CPU = re.compile(
    r"^(\S+Z) \[ci-esta-job-cpu\] start_ms=(\d{1,16}) end_ms=(\d{1,16}) used_usec=(\d{1,20})( scope=job-cgroup)?\r?$", re.MULTILINE,
)


def measure_job_counter(job: ObservedJobV1, names: Set[str], log: str, allocation: RunnerCpuAllocation,
                        *, job_cgroup: bool) -> None:
    # GitHub reports step bounds to the second. Each reading must fall in the
    # main step and its own post step. Multiple invocations can overlap.
    if "[ci-esta-job-cpu] " not in log:
        return
    steps = job.steps
    for match in JOB_CPU.finditer(log):
        if bool(match[5]) != job_cgroup:
            continue
        logged = datetime.fromisoformat(match[1]).timestamp()
        start, end = int(match[2]) / 1000, int(match[3]) / 1000
        elapsed = end - start
        if not allocation.covered_seconds < elapsed <= allocation.occupied_seconds:
            continue
        for step in steps:
            if step.name not in names or not step.started_at or not step.completed_at:
                continue
            if not step.started_at.timestamp() <= start < step.completed_at.timestamp() + 1:
                continue
            if any(post.name == f"Post {step.name}" and post.started_at and post.completed_at
                   and post.started_at.timestamp() <= min(end, logged)
                   and max(end, logged) < post.completed_at.timestamp() + 1 for post in steps):
                # A cumulative counter spans even long gaps. Two readings
                # give total CPU, while only the periodic sampler gives a peak.
                allocation.covered_seconds = elapsed
                allocation.used_core_seconds = int(match[4]) / 1_000_000
                break


def measure_log(job: ObservedJobV1, step_names: Set[str], read_job_log: Callable[[int], str],
                allocation: RunnerCpuAllocation, *, job_cgroup: bool) -> None:
    assert job.started_at and job.completed_at
    # An action with a custom display name can opt in through resource_steps.
    # Local actions and forks retain their default Actions step name.
    step_names = step_names.union(
        s.name for s in job.steps if s.name == "Measure runner CPU" or (
            s.name.startswith("Run ") and s.name.partition("@")[0].endswith("/actions/measure-runner-cpu")
        )
    )
    windows = [(max(step.started_at, job.started_at).timestamp(), min(step.completed_at, job.completed_at).timestamp())
               for step in job.steps if step.name in step_names and step.started_at and step.completed_at]
    if not windows:
        return
    try:
        log = read_job_log(job.job_id)
        if not job_cgroup:
            # Periodic command samples use the VM root, which is shared on slim.
            for counter in resource_counters(log):
                for start, end in windows:
                    if start <= counter.values[0][0] < end:
                        measure(counter, start, end, allocation)
                        break
        measure_job_counter(job, step_names, log, allocation, job_cgroup=job_cgroup)
    except (httpx.HTTPError, ValueError, OverflowError):
        # Optional diagnostics must never stop an otherwise complete report.
        return


def collect(jobs: list[ObservedJobV1], rates: list[RunnerSkuRateV1], url: str | None, namespace: str,
            *, repository_private: bool | None = None, resource_steps: Set[str] = frozenset(),
            read_job_log: Callable[[int], str] | None = None) -> list[ObservedJobV1]:
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
            sku = rate.sku if rate else STANDARD_LABEL_SKUS.get(label, "")
            dedicated_vm = (standard_hosted and sku in {"actions_linux", "actions_linux_arm"}
                            or sku in GITHUB_SKU_PRICES and sku.startswith("linux_"))
            slim = standard_hosted and label == "ubuntu-slim" and sku == "actions_linux_slim"
            if (dedicated_vm or slim) and read_job_log:
                measure_log(job, resource_steps, read_job_log, allocation, job_cgroup=slim)
                if allocation.covered_seconds:
                    return allocated_job
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
    details = ["Unused = covered reservation minus measured CPU time. Bursts above reservation appear as negative values. "
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

