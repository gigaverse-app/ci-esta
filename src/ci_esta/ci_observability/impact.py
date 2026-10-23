"""Explicit benchmark pairs, measured from GitHub rather than supplied savings numbers."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ci_esta.ci_observability import markdown


class RunReference(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    run_id: int = Field(gt=0)
    run_attempt: int = Field(ge=1)
    head_sha: str = Field(pattern=r"^[0-9a-f]{40}$")


class ImpactComparison(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    label: str = Field(min_length=1, max_length=100)
    metric: Literal["gate", "runner", "steps"]
    before: RunReference
    after: RunReference
    job: str | None = Field(default=None, max_length=200)
    steps: list[str] = Field(default_factory=list, max_length=10)
    context: str = Field(min_length=1, max_length=400)
    comparison: Literal["same_head", "workflow_change"] = "same_head"

    @model_validator(mode="after")
    def comparable(self):
        if self.comparison == "same_head" and self.before.head_sha != self.after.head_sha:
            raise ValueError("same-head comparisons require identical revisions")
        if self.metric in {"gate", "steps"} and not self.job:
            raise ValueError("gate and step measurements need an exact job name")
        if self.metric == "steps" and (not self.steps or len(set(self.steps)) != len(self.steps)):
            raise ValueError("step measurements need unique exact step names")
        return self


class ImpactResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    request: ImpactComparison
    before_seconds: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    after_seconds: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    error: str | None = None


def _seconds(start, end):
    if start is None or end is None or end < start:
        raise ValueError("measurement timestamps unavailable or invalid")
    return (end - start).total_seconds()


def _measure(request, run, jobs):
    if run.status != "completed" or run.conclusion != "success":
        raise ValueError("benchmark run did not complete successfully")
    if not jobs or any(job.run_attempt != run.run_attempt for job in jobs):
        raise ValueError("missing jobs or mismatched attempt")
    if any(job.conclusion not in {"success", "skipped"} for job in jobs):
        raise ValueError("benchmark contains unsuccessful jobs")
    if request.metric == "runner":
        return sum(_seconds(job.started_at, job.completed_at) for job in jobs if job.conclusion != "skipped")
    matches = [job for job in jobs if job.name == request.job and job.conclusion == "success"]
    if len(matches) != 1:
        raise ValueError("benchmark job missing, ambiguous or unsuccessful")
    job = matches[0]
    if request.metric == "gate":
        start = run.created_at if run.run_attempt == 1 else run.run_started_at
        return _seconds(start, job.completed_at)
    total = 0.0
    for name in request.steps:
        matches = [step for step in job.steps if step.name == name and step.conclusion == "success"]
        if len(matches) != 1:
            raise ValueError(f"benchmark step missing, ambiguous or unsuccessful: {name}")
        total += _seconds(matches[0].started_at, matches[0].completed_at)
    return total


def collect_impact(client, requests: list[ImpactComparison]) -> list[ImpactResult]:
    cache = {}
    results = []
    for request in requests:
        try:
            samples = []
            workflows = []
            for ref in (request.before, request.after):
                key = (ref.run_id, ref.run_attempt)
                if key not in cache:
                    cache[key] = (client.get_run(ref.run_id, run_attempt=ref.run_attempt),
                                  client.list_jobs(ref.run_id, include_all_attempts=False, run_attempt=ref.run_attempt))
                run, jobs = cache[key]
                # Never turn a rerun, changed revision or missing timestamp into a claimed improvement.
                if (run.id, run.run_attempt, run.head_sha) != (ref.run_id, ref.run_attempt, ref.head_sha):
                    raise ValueError("benchmark source identity mismatch")
                workflows.append((run.workflow_id, run.name))
                samples.append(_measure(request, run, jobs))
            if workflows[0] != workflows[1]:
                raise ValueError("benchmark runs belong to different workflows")
            results.append(ImpactResult(request=request, before_seconds=samples[0], after_seconds=samples[1]))
        except Exception as error:
            results.append(ImpactResult(request=request, error=str(error)[:400]))
    return results


def render_impact(results: list[ImpactResult], repository: str) -> str:
    from ci_esta.ci_observability.enrichment.primitives import format_seconds
    if not results:
        return ""
    lines = ["#### Measured impact", "",
             "Recorded benchmark pairs, rechecked against GitHub. These are historical measurements, "
             "not a prediction for this run. Lower is better; rows can overlap and must not be added.", "",
             "| Change / metric | Before | After | Reduction |", "| :-- | --: | --: | --: |"]
    notes = []
    for result in results:
        item = result.request
        label = markdown.cell(markdown.inline(item.label))
        if result.error:
            lines.append(f"| {label} | unavailable | unavailable | — |")
            notes.append(f"- {label}: {markdown.inline(result.error)}")
            continue
        before, after = result.before_seconds, result.after_seconds
        assert before is not None and after is not None
        def link(ref, seconds):
            value = "<1s" if seconds == 0 else format_seconds(seconds)
            return f"[{value}](https://github.com/{repository}/actions/runs/{ref.run_id}/attempts/{ref.run_attempt})"
        reduction = f"{(before - after) / before * 100:.1f}%" if before else "—"
        lines.append(f"| {label} | {link(item.before, before)} | {link(item.after, after)} | {reduction} |")
        notes.append(f"- **{label}** ({item.comparison.replace('_', ' ')}): {markdown.inline(item.context)}")
    return "\n".join([*lines, "", "<details><summary>Benchmark scope and evidence</summary>", "", *notes,
                      "", "API step timestamps have one-second resolution; <1s means a measured zero-second interval.",
                      "", "</details>", ""])
