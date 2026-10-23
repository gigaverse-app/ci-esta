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
from ci_esta.ci_observability.brand import BLUE, SELECTIVE_URL, Badge
from ci_esta.ci_observability.job_names import job_family
from ci_esta.ci_observability.models import GitHubJobV1, GitHubRunV1, LaneSelectionSectionV1, SkippedLaneReferenceV1

#: Reasons listed per lane before the rest are counted: GitHub caps a comment at 65,536 characters.
LISTED_REASONS = 3
#: A fallback reason can carry an error message; the sticky shows its start.
REASON_CHARACTERS = 300
NO_REASON = "no affected tests or changed inputs"
FULL_SUITE_FALLBACK = "full-suite fallback"
GLOBAL_INPUT = "global input: "
#: The lane strip's squares: a lane that ran, and one that was skipped.
RAN_SQUARE, SKIPPED_SQUARE = "🟧", "⬜"
#: Lanes drawn in the strip before the rest are counted.
STRIP_LANES = 30


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


def badges(section: LaneSelectionSectionV1) -> list[Badge]:
    """The sticky's badges for the lane plan: what ran, and what skipping saved."""
    plan = section.plan
    return [Badge("selected", f"{len(ran_lanes(plan))} / {len(plan.lanes)} lanes", BLUE)]


def strip(plan: LanePlan) -> str:
    """One square per lane, ran first: the plan at a glance, in any theme."""
    shown = sorted(plan.lanes.values(), reverse=True)[:STRIP_LANES]
    more = f" +{len(plan.lanes) - STRIP_LANES}" if len(plan.lanes) > STRIP_LANES else ""
    return "".join(RAN_SQUARE if selected else SKIPPED_SQUARE for selected in shown) + more


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
        return f"⚠️ Every lane was selected because planning fell back: {markdown.inline(plan.reason[:REASON_CHARACTERS])}."
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
            return f"Every lane was selected: {listed}{more} is a CI or dependency input every lane reads."
        return f"Every lane was selected: {markdown.inline(plan.reason[:REASON_CHARACTERS])}."
    changed = len(plan.changed)
    files = f"{changed} changed file{'s' if changed != 1 else ''}"
    if not ran:
        return f"No lane reads the {files}: no test lane was selected."
    names = ", ".join(markdown.code(name) for name in ran)
    return f"The {files} {'reaches' if changed == 1 else 'reach'} {names}; the other lanes were not selected."


def _lane_table(plan: LanePlan) -> list[str]:
    rows = [
        f"| {markdown.cell(markdown.code(name))} | {'selected' if selected else 'not selected'} | "
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
    summary = f"🧪 Test lanes · {ran} / {len(plan.lanes)} selected"
    lines = [
        f"<details><summary>{summary}</summary>",
        "",
        f"#### 🧪 Test lanes · by [pytest-selective]({SELECTIVE_URL})",
        "",
        f"{strip(plan)} · {len(plan.changed)} changed files. These are planning decisions; "
        "receipt reuse and execution outcomes are reported separately.",
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
        *( ["", f"Historical cost of skipped jobs: ≈{_minutes(section.reference.runner_seconds)}. "
             "This comparison can overlap receipt reuse and must not be added to it."] if section.reference else []),
        "",
        "</details>",
    ]
    return "\n".join(lines).rstrip() + "\n"
