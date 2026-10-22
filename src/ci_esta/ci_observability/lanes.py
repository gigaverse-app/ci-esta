"""
Render the lane section of the CI sticky, from a pytest-selective lane plan.

A lane is a whole CI job (or matrix) that pytest-selective runs or skips as a unit, so its
conformance evidence stays complete. The section mirrors the file-selection section: a one-row
TLDR, one sentence with the thing to know, then the per-lane reasons behind a closed expander.

What skipping saved is an estimate: the runner time the skipped jobs took on the default branch's
last green push run, which runs every lane. Lane plans come from whoever opened the PR, so every
path and reason goes through `markdown`.
"""

from __future__ import annotations

from pytest_selective.ci import LanePlan

from ci_esta.ci_observability import markdown
from ci_esta.ci_observability.brand import SELECTIVE_URL
from ci_esta.ci_observability.models import GitHubJobV1, GitHubRunV1, LaneSelectionSectionV1, SkippedLaneReferenceV1

#: Reasons listed per lane before the rest are counted: GitHub caps a comment at 65,536 characters.
LISTED_REASONS = 3
#: A fallback reason can carry an error message; the sticky shows its start.
REASON_CHARACTERS = 300
NO_REASON = "no affected tests or changed inputs"
FULL_SUITE_FALLBACK = "full-suite fallback"
GLOBAL_INPUT = "global input: "


def job_family(name: str) -> str:
    """
    A job's name without its matrix suffix.

    GitHub names an expanded matrix job `tests (3.11)` but a skipped matrix, which never expands,
    `tests (${{ matrix.python }})`: both belong to the family `tests`.
    """
    return name.split(" (", 1)[0]


def skipped_reference(
    jobs: list[GitHubJobV1], reference_run: GitHubRunV1, reference_jobs: list[GitHubJobV1]
) -> SkippedLaneReferenceV1 | None:
    """
    The runner time the reference run spent in the job families this run skipped entirely.

    A family that also executed here is left out: part of it ran, and the sticky cannot tell
    which part. Only green, timed reference jobs count.
    """
    skipped = {job_family(job.name) for job in jobs if job.conclusion == "skipped"}
    skipped -= {job_family(job.name) for job in jobs if job.conclusion != "skipped"}
    matched = {
        job.name: (job.completed_at - job.started_at).total_seconds()
        for job in reference_jobs
        if job_family(job.name) in skipped
        and job.conclusion == "success"
        and job.started_at is not None
        and job.completed_at is not None
        and job.completed_at >= job.started_at
    }
    if not matched or reference_run.head_branch is None:
        return None
    return SkippedLaneReferenceV1(
        run_id=reference_run.id,
        head_branch=reference_run.head_branch,
        jobs=list(matched),
        runner_seconds=sum(matched.values()),
    )


def _minutes(seconds: float) -> str:
    minutes = seconds / 60
    return f"{minutes:.0f} runner-min" if minutes >= 1 else f"{seconds:.0f} runner-s"


def ran_lanes(plan: LanePlan) -> list[str]:
    return [name for name, selected in plan.lanes.items() if selected]


def headline(section: LaneSelectionSectionV1) -> str:
    """The sticky's verdict-line fragment: what ran, and what skipping saved."""
    plan = section.plan
    text = f"ran **{len(ran_lanes(plan))} of {len(plan.lanes)}** test lanes"
    if section.reference is not None:
        text += f" (≈{_minutes(section.reference.runner_seconds)} skipped)"
    return text


def _reason(reason: str) -> str:
    """`affected test: tests/x.py` -> affected test `tests/x.py`; free text stays text."""
    kind, separator, path = reason.partition(": ")
    if not separator or kind.startswith(FULL_SUITE_FALLBACK):
        return markdown.cell(markdown.inline(reason[:REASON_CHARACTERS]))
    return f"{markdown.cell(markdown.inline(kind))} {markdown.cell(markdown.code(path))}"


def _reasons(reasons: list[str]) -> str:
    shown = [_reason(reason) for reason in reasons[:LISTED_REASONS]]
    if len(reasons) > LISTED_REASONS:
        shown.append(f"+{len(reasons) - LISTED_REASONS} more")
    return "<br>".join(shown)


def _takeaway(plan: LanePlan) -> str:
    ran = ran_lanes(plan)
    if plan.reason.startswith(FULL_SUITE_FALLBACK):
        return f"⚠️ Every lane ran because planning fell back: {markdown.inline(plan.reason[:REASON_CHARACTERS])}."
    if ran and len(ran) == len(plan.lanes):
        global_paths = sorted(
            {
                reason.removeprefix(GLOBAL_INPUT)
                for reasons in plan.lane_reasons.values()
                for reason in reasons
                if reason.startswith(GLOBAL_INPUT)
            }
        )
        if global_paths:
            listed = ", ".join(markdown.code(path) for path in global_paths[:LISTED_REASONS])
            more = f" and {len(global_paths) - LISTED_REASONS} more" if len(global_paths) > LISTED_REASONS else ""
            return f"Every lane ran: {listed}{more} is a CI or dependency input every lane reads."
        return f"Every lane ran: {markdown.inline(plan.reason[:REASON_CHARACTERS])}."
    changed = len(plan.changed)
    files = f"{changed} changed file{'s' if changed != 1 else ''}"
    if not ran:
        return f"No lane reads the {files}: every test lane was skipped."
    names = ", ".join(markdown.code(name) for name in ran)
    return f"The {files} {'reaches' if changed == 1 else 'reach'} {names}; the other lanes were skipped."


def _lane_table(plan: LanePlan) -> list[str]:
    rows = [
        f"| {markdown.cell(markdown.code(name))} | {'ran' if selected else 'skipped'} | "
        f"{_reasons(plan.lane_reasons.get(name, [NO_REASON]))} |"
        # Lanes that ran first: they are the ones a reader asks about.
        for name, selected in sorted(plan.lanes.items(), key=lambda item: not item[1])
    ]
    return ["| Lane | | Because |", "|:--|:--|:--|", *rows]


def _reference_note(section: LaneSelectionSectionV1, repository: str | None) -> list[str]:
    reference = section.reference
    if reference is None:
        return []
    run = f"run {reference.run_id}"
    if repository is not None:
        run = f"[{run}](https://github.com/{repository}/actions/runs/{reference.run_id})"
    jobs = len(reference.jobs)
    return [
        f"<sub>Skipped is the runner time the skipped jobs took on the last green "
        f"{markdown.code(reference.head_branch)} push, which runs every lane ({run}, "
        f"{jobs} job{'s' if jobs != 1 else ''}). An estimate, not billed minutes.</sub>",
    ]


def render_lane_section(section: LaneSelectionSectionV1, repository: str | None = None) -> str:
    """The sticky's lane section, as GitHub-flavored Markdown; `repository` links runs."""
    plan = section.plan
    ran = len(ran_lanes(plan))
    skipped = _minutes(section.reference.runner_seconds) if section.reference is not None else "—"
    lines = [
        f"#### 🧪 Test lanes · by [pytest-selective]({SELECTIVE_URL})",
        "",
        "| Ran | Skipped | Changed files | Skipped work |",
        "|:--|--:|--:|--:|",
        f"| {ran} of {len(plan.lanes)} lanes | {len(plan.lanes) - ran} | {len(plan.changed)} | {skipped} |",
        "",
        _takeaway(plan),
        "",
        "<details><summary>Why these lanes?</summary>",
        "",
        *_lane_table(plan),
        "",
        "</details>",
        "",
        *_reference_note(section, repository),
    ]
    return "\n".join(lines).rstrip() + "\n"
