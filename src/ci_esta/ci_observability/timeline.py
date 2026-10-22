"""
Render the sticky's CI timeline as a Mermaid gantt chart.

Each job is one row, named in the left column; its bar is its run, labeled with how long it took
and how long it first waited for a runner. Orange marks the chain the merge waited on, and a
milestone marks merge-ready. GitHub's Mermaid ignores `displayMode: compact`, so a wait cannot
share its job's row as a bar of its own.

The chain comes from the critical-path analysis of the workflow's `needs` graph when it is
complete. Without it, the chain is inferred from timestamps: GitHub creates a job when the jobs
it needs complete, so a job's predecessor is the one that finished just before it was created.
The footnote says which source drew the chain. Bars are observed API timestamps.
"""

from __future__ import annotations

import json
import math
from datetime import datetime, timedelta

from ci_esta.ci_observability.enrichment.primitives import format_seconds
from ci_esta.ci_observability.lanes import job_family
from ci_esta.ci_observability.models import CiObservabilityReportV1, ObservedJobV1, TimingStatus

#: A predecessor finished at most this long before its successor was created...
CHAIN_GAP_SECONDS = 15.0
#: ...or this long after: GitHub's timestamps have second precision and are not ordered exactly.
CHAIN_SLACK_SECONDS = 3.0
#: Waits shorter than this are not shown: they are noise at the chart's scale.
SHOWN_QUEUE_SECONDS = 5.0
#: Row labels are cut to this many characters; the left column is fixed width.
LABEL_CHARACTERS = 32
#: Bars are dates on a fixed origin, not bare seconds: GitHub's Mermaid does not parse `dateFormat X`
#: start times, and drew every bar from the axis origin.
ORIGIN = datetime(2000, 1, 1)
DATE_FORMAT = "YYYY-MM-DD HH:mm:ss"

#: GitHub renders the chart on its own light or dark background, so every color has to read on
#: both: saturated bars with white text, and mid-grey text outside them.
THEME = {
    "theme": "base",
    "themeVariables": {
        "fontFamily": "-apple-system, BlinkMacSystemFont, Segoe UI, Helvetica, Arial, sans-serif",
        "fontSize": "13px",
        "doneTaskBkgColor": "#3B82F6",
        "doneTaskBorderColor": "#2563EB",
        "critBkgColor": "#EA580C",
        "critBorderColor": "#C2410C",
        "taskBkgColor": "#3B82F6",
        "taskBorderColor": "#2563EB",
        "taskTextColor": "#FFFFFF",
        "taskTextDarkColor": "#FFFFFF",
        "taskTextLightColor": "#FFFFFF",
        "taskTextOutsideColor": "#8B949E",
        "titleColor": "#8B949E",
        "sectionBkgColor": "rgba(234, 88, 12, 0.07)",
        "altSectionBkgColor": "rgba(139, 148, 158, 0.05)",
        "sectionBkgColor2": "rgba(234, 88, 12, 0.07)",
        "gridColor": "rgba(139, 148, 158, 0.3)",
        "todayLineColor": "rgba(0, 0, 0, 0)",
    },
    "gantt": {
        "barHeight": 20,
        "barGap": 6,
        "topPadding": 44,
        "leftPadding": 230,
        # GitHub overlays its zoom and pan buttons on the chart's right edge; keep the bars clear of them.
        "rightPadding": 140,
        "sectionFontSize": 13,
        "fontSize": 12,
    },
}


def _label(value: str) -> str:
    """
    Mermaid ends a task's label at a colon and treats `#` and `;` as syntax.

    A long name is cut in the middle: its start says what it is, and its end tells shards and
    matrix legs apart.
    """
    for character in (":", "#", ";"):
        value = value.replace(character, " ")
    value = " ".join(value.split())
    if len(value) <= LABEL_CHARACTERS:
        return value
    head = LABEL_CHARACTERS // 2
    return value[:head] + "…" + value[-(LABEL_CHARACTERS - head - 1) :]


def _timed(report: CiObservabilityReportV1) -> list[ObservedJobV1]:
    return [
        job
        for job in report.latest_attempt_jobs
        if job.start_offset_seconds is not None
        and job.end_offset_seconds is not None
        and job.end_offset_seconds > job.start_offset_seconds
    ]


def _ready_at(job: ObservedJobV1) -> float:
    """When the job became runnable: created, or started when GitHub gave no creation time."""
    if job.queued_offset_seconds is not None:
        return job.queued_offset_seconds
    assert job.start_offset_seconds is not None, "timed jobs have a start"
    return job.start_offset_seconds


def critical_chain(jobs: list[ObservedJobV1], merge_ready_seconds: float | None) -> list[ObservedJobV1]:
    """
    The jobs the merge waited on, first to last, inferred from timestamps.

    The chain ends at the last job to finish by merge-ready (or at all), and walks back through
    the job that finished just before each one was created.
    """
    ends = [job for job in jobs if job.end_offset_seconds is not None]
    if merge_ready_seconds is not None:
        ends = [job for job in ends if (job.end_offset_seconds or 0) <= merge_ready_seconds + CHAIN_SLACK_SECONDS]
    if not ends:
        return []
    current = max(ends, key=lambda job: (job.end_offset_seconds or 0, job.name))
    chain = [current]
    while True:
        ready = _ready_at(current)
        predecessors = [
            job
            for job in jobs
            if job not in chain
            and job.end_offset_seconds is not None
            and ready - CHAIN_GAP_SECONDS <= job.end_offset_seconds <= ready + CHAIN_SLACK_SECONDS
        ]
        if not predecessors:
            return list(reversed(chain))
        current = max(predecessors, key=lambda job: (job.end_offset_seconds or 0, job.name))
        chain.append(current)


def _row_label(job: ObservedJobV1) -> str:
    """The job's name for the left column; a matrix leg reads `tests · 3.14, ubuntu-latest`."""
    # A reusable workflow's jobs share its caller's prefix (`Contracts / Suite · 1`); keep the job's own name.
    name = job.name.rsplit(" / ", 1)[-1]
    family = job_family(name)
    if name != family and name.endswith(")"):
        name = f"{family} · {name[len(family) + 2 : -1]}"
    return _label(name + (" (running)" if job.timing_status == TimingStatus.ACCRUED else ""))


def _at(offset: int) -> str:
    """An offset from workflow creation as a date on a fixed origin, so the axis reads minutes:seconds."""
    return (ORIGIN + timedelta(seconds=offset)).strftime("%Y-%m-%d %H:%M:%S")


def _bar_label(job: ObservedJobV1) -> str:
    """How long the job ran, and how long it first waited for a runner when that was noticeable."""
    label = format_seconds(job.wall_seconds) if job.wall_seconds is not None else "running"
    queued, start = job.queued_offset_seconds, job.start_offset_seconds
    if queued is not None and start is not None and start - queued >= SHOWN_QUEUE_SECONDS:
        label += f" · ⏳ {format_seconds(start - queued)}"
    return label


def _chain(report: CiObservabilityReportV1, jobs: list[ObservedJobV1]) -> tuple[set[int], bool]:
    """
    The jobs to mark orange, and whether they come from the workflow's dependency graph.

    The critical-path analysis reads the workflow's `needs` and is authoritative when it is
    complete; timestamps stand in only when the graph is unavailable.
    """
    path = report.critical_path
    if path is not None and path.status == "complete":
        names = set(path.observed_path)
        return {job.job_id for job in jobs if job.name in names}, True
    return {job.job_id for job in critical_chain(jobs, report.merge_ready_from_creation_seconds)}, False


def render_timeline(report: CiObservabilityReportV1) -> list[str]:
    jobs = _timed(report)
    merge_ready = report.merge_ready_from_creation_seconds
    if not jobs and merge_ready is None:
        return []
    chain, from_graph = _chain(report, jobs)
    title = (
        f"{format_seconds(merge_ready)} to merge-ready · orange is what the merge waited on"
        if merge_ready is not None
        else "CI jobs from workflow creation · orange is the longest chain"
    )
    latest = max([*(job.end_offset_seconds or 0 for job in jobs), merge_ready or 0])
    lines = [
        "```mermaid",
        f"%%{{init: {json.dumps(THEME)}}}%%",
        "gantt",
        f"    title {title}",
        f"    dateFormat {DATE_FORMAT}",
        f"    axisFormat {'%H:%M:%S' if latest >= 3600 else '%M:%S'}",
        "    todayMarker off",
    ]
    # Each job is its own section, so it gets one row beside its name.
    for index, job in enumerate(sorted(jobs, key=lambda item: (_ready_at(item), item.start_offset_seconds, item.name))):
        start, end = int(job.start_offset_seconds or 0), int(job.end_offset_seconds or 0)
        lines.append(f"    section {_row_label(job)}")
        tag = "crit" if job.job_id in chain else "done"
        lines.append(f"    {_bar_label(job)} :{tag}, j{index}, {_at(start)}, {_at(max(end, start + 1))}")
    if merge_ready is not None:
        ready = _at(math.ceil(merge_ready))
        lines += [
            "    section ✅ merge-ready",
            f"    {format_seconds(merge_ready)} :milestone, crit, m, {ready}, {ready}",
        ]
    source = (
        "the critical path through the workflow's `needs` graph"
        if from_graph
        else "the chain of jobs that set the finish time, inferred from when each job was created and its "
        "predecessor finished"
    )
    footnote = f"⏳: how long a job waited for a runner. Orange: {source}. Bars are observed API timestamps."
    return [*lines, "```", "", f"<sub>{footnote}</sub>", ""]
