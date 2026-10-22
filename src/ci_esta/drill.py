"""
Live CI drill: prove a CI change on real GitHub, across backend-common and both consumers, before it merges.

A generated bump PR proves only that one event on one commit passes. That is how #210 and
#211 merged while the same-head reuse they claimed never fired. The drill runs the events
that matter against a consumer branch, on GitHub itself, and scores the outcome:

- a validation job that passed on the commit and runs again is repeated work;
- only jobs a consumer profile declares, each with its reason, may run every time;
- every run's own verdict must be green.

It drills the generated ``update-backend-common-pr<N>`` branch, whose CI runs the unmerged
backend-common change through the movable ``PR<N>`` ref. With ``--compare-main`` it drills
each consumer's ``main`` side by side and reports whether the change improved, kept or
regressed CI, so an improvement is proven before merge, not discovered after::

    python -m ci_esta.drill --source-pr 216 --compare-main --expect improved

The default reuses twelve existing PR slots (consumer × comparison arm × family),
driven with ``gh`` under the caller's credentials (``GH_TOKEN``). Slots close when idle
and retain their refs. ``--fresh-pr`` explicitly creates throwaways to test opened events.
Exit status is non-zero when the expectation is not met.

Three families of drill run side by side:

- ``retrigger``: re-trigger the validated commit (``SCENARIOS``) and score repeated work;
- ``main-moved``: validate the PR, move its base under it with a change every test reaches,
  merge that base in the way the bump automation merges consumer main, and score how many
  tests the next run selects. The PR targets a drill-owned copy of main, so the drill decides
  what main changed and never touches the real one.
- ``retag``: validate the PR, then move its backend-common pin to a new tag of an identical
  tree, the way merging the source PR retags ``PR<N>`` to ``v<N>``, and score what reruns.
  The tag points at a drill-made commit and is deleted when the drill ends.

Repeat and retag PRs target a frozen copy of main. An unrelated merge during the
drill must not turn correct base invalidation into a false repeated-work failure.

Add a scenario to ``SCENARIOS`` (and its action to ``ACTIONS``) to drill a new event.
"""

from __future__ import annotations

import argparse
import base64
import concurrent.futures
import datetime as dt
import fnmatch
import json
import os
import re
import signal
import socket
import subprocess
import sys
import threading
import time
import uuid
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager, nullcontext
from typing import Literal, TypeVar

import yaml
from pydantic import BaseModel, ConfigDict

ORG = "gigaverse-app"
SOURCE_REPOSITORY = f"{ORG}/backend-common"
STATUS_CONTEXT = "ci-drill"
POLL_SECONDS = 15
RUN_TIMEOUT_SECONDS = 40 * 60
# A re-run slower than baseline by more than this, and by the margin below, is a regression.
SLOWER_RATIO = 1.25
FASTER_RATIO = 0.8
NOISE_SECONDS = 30.0
# Job names carry the shard count, and a skipped job's name is left unrendered, so
# "Run pytest (3 concurrent shards)" and "Run pytest (${{ ... }} concurrent shards)" are one job.
SHARD_COUNT = re.compile(r"(?:\d+|\$\{\{.*?\}\}) concurrent shards")
# The shared test-impact action's summary line, printed in the plan job's log.
SELECTION_LINE = re.compile(r"Test impact: (\d+)/(\d+) files; (\w+)")
RESOLVER_LINES = re.compile(
    r"(Candidate run \d+ .* rejected: .*|Reusing successful PR evidence.*|"
    r"Validated evidence candidate.*|No fresh successful ancestor.*|Ignoring successful .* contained.*)"
)


class DrillModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class AlwaysRuns(DrillModel):
    """A job that legitimately runs on every event, and why."""

    pattern: str
    reason: str


class ConsumerProfile(DrillModel):
    repository: str
    workflow: str
    plan_job: str
    pytest_job: str
    touch_path: str
    #: A module every test reaches: the main-moved drill edits it on the drill's copy of main.
    broad_path: str
    always_runs: tuple[AlwaysRuns, ...]
    #: Jobs a retag legitimately re-runs, each with why: the lock's text did change.
    retag_reruns: tuple[AlwaysRuns, ...] = ()

    def always(self, job: str) -> bool:
        return any(fnmatch.fnmatchcase(job, rule.pattern) for rule in self.always_runs)

    def reruns_on_retag(self, job: str) -> bool:
        return any(fnmatch.fnmatchcase(job, rule.pattern) for rule in self.retag_reruns)


class Scenario(DrillModel):
    """One event applied to the already-validated commit, after an optional wait."""

    key: str
    label: str
    action: Literal["ready"]
    delay_seconds: int
    #: Run only with --thorough: slow, and covering a failure mode a unit test already pins.
    thorough: bool = False


class JobOutcome(DrillModel):
    name: str
    conclusion: str | None
    seconds: float | None = None


class Selection(DrillModel):
    """How many test files a run's planner selected, out of how many."""

    selected: int
    total: int
    mode: str


def parse_selection(log: str) -> Selection | None:
    """The last selection summary in a plan log."""
    matches = SELECTION_LINE.findall(log)
    if not matches:
        return None
    selected, total, mode = matches[-1]
    return Selection(selected=int(selected), total=int(total), mode=mode)


def _secs(value: float | None) -> str:
    return "?" if value is None else f"{value:.0f}s"


# The plan job gates every other job, so its time is on every run's critical path.
PLAN_NOISE_SECONDS = 10.0


class RunOutcome(DrillModel):
    label: str
    run_id: int | None
    jobs: tuple[JobOutcome, ...]
    conclusion: str | None = "success"
    wall_seconds: float | None = None
    resolver_lines: tuple[str, ...] = ()
    selection: Selection | None = None
    plan_seconds: float | None = None


class Repetition(DrillModel):
    scenario: str
    job: str
    conclusion: str | None


RETAG_LABEL = "retag to an identical tree"


class Scorecard(DrillModel):
    consumer: str
    base: str
    family: Literal["retrigger", "retag"] = "retrigger"
    head_sha: str
    runs: tuple[RunOutcome, ...]
    validated: tuple[str, ...]
    repeated: tuple[Repetition, ...]
    red_runs: tuple[str, ...]

    @property
    def passed(self) -> bool:
        return not self.repeated and not self.red_runs

    @property
    def retrigger_seconds(self) -> float:
        return sum(run.wall_seconds or 0.0 for run in self.runs[1:])

    def markdown(self) -> str:
        drilled = "" if self.family == "retrigger" else f", {self.family}"
        lines = [
            f"#### {self.consumer} from `{self.base}`{drilled}: {'PASS' if self.passed else 'FAIL'}",
            "",
            f"Head `{self.head_sha[:9]}`; {len(self.validated)} validation jobs passed on this commit.",
            "",
            "| Scenario | Run | Verdict | Wall | Plan | Repeated validation jobs |",
            "|---|---|---|---|---|---|",
        ]
        for run in self.runs:
            repeated = [item.job for item in self.repeated if item.scenario == run.label]
            wall = f"{run.wall_seconds:.0f}s" if run.wall_seconds is not None else "?"
            lines.append(
                f"| {run.label} | {run.run_id if run.run_id is not None else 'no run'} | {run.conclusion} | {wall} | {_secs(run.plan_seconds)} "
                f"| {', '.join(repeated) or '—'} |"
            )
        for run in self.runs:
            if run.resolver_lines:
                # Reused PRs accumulate rejected historical candidates. Keep the complete
                # evidence in RunOutcome/JSON and the immutable Actions log, not a huge PR comment.
                ordered = sorted(run.resolver_lines, key=lambda line: line.startswith("Candidate run "))
                excerpt = "\n".join(ordered)
                if len(excerpt) > 1000:
                    excerpt = excerpt[:1000] + "\n… excerpt truncated; see full run log"
                lines += [
                    "",
                    f"Resolver, {run.label}:",
                    "```",
                    excerpt,
                    "```",
                    f"[Full run log](https://github.com/{self.consumer}/actions/runs/{run.run_id})",
                ]
        return "\n".join(lines)


class DrillFailure(DrillModel):
    """A drill that could not finish; it fails the expectation instead of hiding the others."""

    consumer: str
    base: str
    error: str


Verdict = Literal["improved", "unchanged", "regressed"]


class Comparison(DrillModel):
    """The candidate branch against the consumer's main, drilled the same way."""

    baseline: Scorecard
    candidate: Scorecard
    verdict: Verdict
    reasons: tuple[str, ...]


class MainMovedCard(DrillModel):
    """A validated PR, then the run after main moved under it and was merged in."""

    consumer: str
    base: str
    runs: tuple[RunOutcome, ...]

    @property
    def after(self) -> RunOutcome:
        return self.runs[-1]

    @property
    def red_runs(self) -> tuple[str, ...]:
        return tuple(run.label for run in self.runs if run.conclusion != "success")

    def markdown(self) -> str:
        lines = [
            f"#### {self.consumer} from `{self.base}`, main moved under a validated PR",
            "",
            "| Run | Id | Verdict | Wall | Plan | Tests selected |",
            "|---|---|---|---|---|---|",
        ]
        for run in self.runs:
            wall = f"{run.wall_seconds:.0f}s" if run.wall_seconds is not None else "?"
            picked = run.selection
            shown = f"{picked.selected}/{picked.total} ({picked.mode})" if picked else "?"
            lines.append(
                f"| {run.label} | {run.run_id if run.run_id is not None else 'no run'} | {run.conclusion} | {wall} | {_secs(run.plan_seconds)} | {shown} |"
            )
        return "\n".join(lines)


class MainMovedComparison(DrillModel):
    baseline: MainMovedCard
    candidate: MainMovedCard
    verdict: Verdict
    reasons: tuple[str, ...]


SCENARIOS = {
    "ready-now": Scenario(key="ready-now", label="ready right after green", action="ready", delay_seconds=0),
    # GitHub's run listing lagged a just-finished run; the check-run fallback covers that and
    # test_a_lagging_listing_is_covered_by_the_head_commits_own_check_runs pins it. Four idle
    # minutes plus a run on every drill buy little beyond that, so it is opt-in.
    "ready-later": Scenario(
        key="ready-later", label="ready again 4 minutes later", action="ready", delay_seconds=4 * 60, thorough=True
    ),
}

SHARED_ALWAYS = (
    AlwaysRuns(pattern="*guard_rerun*", reason="rerun guard; decides nothing about the tree"),
    AlwaysRuns(pattern="Publish *", reason="reporting of the run itself"),
)
PROFILES = {
    "gigaverse-backend": ConsumerProfile(
        repository=f"{ORG}/gigaverse-backend",
        workflow="test.yaml",
        plan_job="Plan test paths",
        pytest_job="Test unit behavior*",
        # Touch a test directly: the old Kafka leaf has no selected dependents now that
        # minimum-file padding is gone, so it no longer exercises pytest reuse at all.
        touch_path="gigaverse/core/shared/tests/test_utils_retry.py",
        # Every test reaches it; a main change to it made #4959 run 750/750 files for a pin bump.
        broad_path="gigaverse/settings.py",
        always_runs=(
            *SHARED_ALWAYS,
            AlwaysRuns(pattern="Plan test paths", reason="decides what this event needs"),
            AlwaysRuns(pattern="Resolve backend check gate", reason="aggregates this run's verdict"),
            AlwaysRuns(pattern="Sync deployment followups*", reason="PR bookkeeping"),
            AlwaysRuns(pattern="Lint OpenAPI compatibility", reason="compares against deployed state, not the tree"),
            AlwaysRuns(
                pattern="Carry the reused test image to this tree",
                reason="copies a reused image to this tree's deploy tag; validates nothing",
            ),
        ),
        retag_reruns=(
            AlwaysRuns(
                pattern="Test unit behavior*",
                reason="test-impact selects the tests that read the lock and manifest text, which changed",
            ),
        ),
    ),
    "gigaverse-ai": ConsumerProfile(
        repository=f"{ORG}/gigaverse-ai",
        workflow="testing.yaml",
        plan_job="Plan default-gate scope",
        pytest_job="Run pytest*",
        # Reached by its own unit test and the three import-boundary tests that reach every module.
        touch_path="src/gv/ai/common/llm/json_parsing_utils.py",
        # The root conftest: an ancestor of every test file.
        broad_path="tests/conftest.py",
        always_runs=(
            *SHARED_ALWAYS,
            AlwaysRuns(pattern="Plan default-gate scope", reason="decides what this event needs"),
            AlwaysRuns(pattern="Python tests gate", reason="aggregates this run's verdict"),
            AlwaysRuns(pattern="Coverage & Test Durations", reason="reporting of the run itself"),
            AlwaysRuns(pattern="Test Results", reason="reporting of the run itself"),
        ),
        retag_reruns=(
            AlwaysRuns(
                pattern="Run pytest*",
                reason="test-impact selects the tests that read the lock and manifest text, which changed",
            ),
            AlwaysRuns(pattern="Source security scan", reason="Semgrep scans the changed lock and manifest text"),
        ),
    ),
}


def job_key(name: str) -> str:
    """One key per job, whatever shard count its name carries or whether it was rendered."""
    return SHARD_COUNT.sub("N concurrent shards", name)


def score(
    profile: ConsumerProfile,
    base: str,
    head_sha: str,
    runs: Sequence[RunOutcome],
    family: Literal["retrigger", "retag"] = "retrigger",
) -> Scorecard:
    """
    Every job that already passed on this commit, in any earlier run, and runs again is repeated work.

    Earlier runs count, not only the first: a draft skips some jobs, so a job first admitted by
    the ready event has validated the commit from then on. A retag changes only the pin's text,
    so after one, only the jobs the profile says read that text may run again.
    """
    passed: list[str] = []
    repeated: list[Repetition] = []
    for run in runs:
        for job in run.jobs:
            key = job_key(job.name)
            expected = run.label == RETAG_LABEL and profile.reruns_on_retag(job.name)
            if key in passed and job.conclusion not in ("skipped", None) and not expected:
                repeated.append(Repetition(scenario=run.label, job=key, conclusion=job.conclusion))
        passed += [
            job_key(job.name)
            for job in run.jobs
            if job.conclusion == "success" and not profile.always(job.name) and job_key(job.name) not in passed
        ]
    validated = tuple(passed)
    red_runs = tuple(run.label for run in runs if run.conclusion != "success")
    return Scorecard(
        consumer=profile.repository,
        base=base,
        family=family,
        head_sha=head_sha,
        runs=tuple(runs),
        validated=validated,
        repeated=tuple(repeated),
        red_runs=red_runs,
    )


def _first_time_jobs(card: Scorecard) -> set[str]:
    """Jobs the re-triggers ran that are not repeats: admitted, not redone."""
    repeated = {item.job for item in card.repeated}
    return {
        job_key(job.name)
        for run in card.runs[1:]
        for job in run.jobs
        if job.conclusion not in ("skipped", None) and job_key(job.name) not in repeated
    }


def compare(baseline: Scorecard, candidate: Scorecard) -> Comparison:
    """
    Improved, unchanged or regressed.

    A regression is a red candidate run, a clear slowdown, or a repeat of a job that main
    validated and did not repeat. A job main also repeats is pre-existing waste, and one main
    never validated has no baseline; both are reported, neither is blamed on the candidate.
    """
    regressions: list[str] = [f"red run on the candidate: {label}" for label in candidate.red_runs]
    notes: list[str] = []
    main_repeats = {item.job for item in baseline.repeated}
    for job in dict.fromkeys(item.job for item in candidate.repeated):
        if job in main_repeats:
            notes.append(f"{job} also repeats on main (pre-existing)")
        elif job in baseline.validated:
            regressions.append(f"repeats {job}, which main validated and reused")
        else:
            notes.append(f"{job} repeats, and main never ran it to compare")
    before, after = baseline.retrigger_seconds, candidate.retrigger_seconds
    # A job a re-trigger runs for the first time was admitted by the PR's own diff (a bump PR
    # changes the lock, so its ready event runs a dependency scan main's drill never does).
    # Wall times that include different such jobs measure the diffs, not the CI change.
    only_candidate = _first_time_jobs(candidate) - _first_time_jobs(baseline)
    only_main = _first_time_jobs(baseline) - _first_time_jobs(candidate)
    comparable = not only_candidate and not only_main
    if not comparable:
        notes.append(
            "re-trigger wall times not comparable: "
            + "; ".join(
                f"only {side} ran {', '.join(sorted(jobs))}"
                for side, jobs in (("the candidate", only_candidate), ("main", only_main))
                if jobs
            )
        )
    if comparable and after > before * SLOWER_RATIO and after - before > NOISE_SECONDS:
        regressions.append(f"re-triggered runs took {after:.0f}s against {before:.0f}s on main")
    # Reported, never a verdict: the candidate's diff always moves the backend-common pin, so its
    # plan also narrows the pin (a clone) and compares a larger diff, which main's drill cannot.
    # backend-common#217's drill: +13s on backend from exactly that, none of it the CI change.
    notes += [note for note in plan_delta(baseline.runs, candidate.runs) if note]
    if regressions:
        return Comparison(baseline=baseline, candidate=candidate, verdict="regressed", reasons=tuple(regressions))
    gains: list[str] = []
    if len(candidate.repeated) < len(baseline.repeated):
        gains.append(f"repeated validation jobs {len(baseline.repeated)} → {len(candidate.repeated)}")
    if comparable and after < before * FASTER_RATIO and before - after > NOISE_SECONDS:
        gains.append(f"re-triggered runs {before:.0f}s → {after:.0f}s")
    return Comparison(
        baseline=baseline,
        candidate=candidate,
        verdict="improved" if gains else "unchanged",
        reasons=(*(gains or ["no measurable difference from main"]), *notes),
    )


def plan_delta(baseline: Sequence[RunOutcome], candidate: Sequence[RunOutcome]) -> tuple[str | None, str | None]:
    """A (regression, gain) pair from the mean plan-job time over every run on each side."""
    before_times = [run.plan_seconds for run in baseline if run.plan_seconds is not None]
    after_times = [run.plan_seconds for run in candidate if run.plan_seconds is not None]
    if not before_times or not after_times:
        return None, None
    before, after = sum(before_times) / len(before_times), sum(after_times) / len(after_times)
    if after > before * SLOWER_RATIO and after - before > PLAN_NOISE_SECONDS:
        return f"plan job took {after:.0f}s against {before:.0f}s on main", None
    if after < before * FASTER_RATIO and before - after > PLAN_NOISE_SECONDS:
        return None, f"plan job {before:.0f}s → {after:.0f}s"
    return None, None


def _growth(card: MainMovedCard) -> int | None:
    """Test files main moving added to the PR's own selection."""
    validated, after = card.runs[0].selection, card.after.selection
    return None if validated is None or after is None else after.selected - validated.selected


def _ran(run: RunOutcome) -> set[str]:
    return {job_key(job.name) for job in run.jobs if job.conclusion not in ("skipped", None)}


def compare_main_moved(baseline: MainMovedCard, candidate: MainMovedCard) -> MainMovedComparison:
    """
    Improved, unchanged or regressed, judged on how much the selection grows when main moves.

    Each PR's own diff selects its own tests before main moves; the bump PR's adaptation
    selects more than main's drill PR does (#218's drill: 22 files against 4, neither
    growing). What a selection change claims is that main moving adds fewer tests. A red run,
    a selection the log does not show, more growth or a clear slowdown is a regression. Wall
    time counts only when both sides ran the same jobs after main moved.
    """
    regressions = [f"red run on the candidate: {label}" for label in candidate.red_runs]
    notes: list[str] = []
    before, after = baseline.after.selection, candidate.after.selection
    grew_before, grew_after = _growth(baseline), _growth(candidate)
    if after is None or grew_after is None:
        regressions.append("the candidate's plan log shows no test selection")
    elif before is not None and grew_before is not None and grew_after > grew_before:
        regressions.append(
            f"selected {after.selected} test files against {before.selected} on main; "
            f"grew by {grew_after} where main grew by {grew_before}"
        )
    jobs_before, jobs_after = _ran(baseline.after), _ran(candidate.after)
    comparable = jobs_before == jobs_after
    if not comparable:
        only = [
            f"only {side} ran {', '.join(sorted(jobs))}"
            for side, jobs in (("the candidate", jobs_after - jobs_before), ("main", jobs_before - jobs_after))
            if jobs
        ]
        notes.append("wall times after main moved not comparable: " + "; ".join(only))
    slow_before, slow_after = baseline.after.wall_seconds or 0.0, candidate.after.wall_seconds or 0.0
    if comparable and slow_after > slow_before * SLOWER_RATIO and slow_after - slow_before > NOISE_SECONDS:
        regressions.append(f"the run after main moved took {slow_after:.0f}s against {slow_before:.0f}s on main")
    # Reported, never a verdict: the candidate's diff always moves the backend-common pin, so its
    # plan also narrows the pin (a clone) and compares a larger diff, which main's drill cannot.
    # backend-common#217's drill: +13s on backend from exactly that, none of it the CI change.
    notes += [note for note in plan_delta(baseline.runs, candidate.runs) if note]
    if regressions:
        return MainMovedComparison(
            baseline=baseline, candidate=candidate, verdict="regressed", reasons=tuple(regressions)
        )
    gains: list[str] = []
    if (
        before is not None
        and after is not None
        and grew_before is not None
        and grew_after is not None
        and grew_after < grew_before
    ):
        gains.append(
            f"tests selected after main moved {before.selected} → {after.selected} of {after.total} "
            f"(main moving added {grew_before} on main, {grew_after} here)"
        )
    if comparable and slow_after < slow_before * FASTER_RATIO and slow_before - slow_after > NOISE_SECONDS:
        gains.append(f"the run after main moved {slow_before:.0f}s → {slow_after:.0f}s")
    return MainMovedComparison(
        baseline=baseline,
        candidate=candidate,
        verdict="improved" if gains else "unchanged",
        reasons=(*(gains or ["no measurable difference from main"]), *notes),
    )


def bump_branch(source_pr: int) -> str:
    return f"update-backend-common-pr{source_pr}"


def require_current_bump(record_json: str, source_head: str, branch: str) -> None:
    """Refuse to drill a bump branch that does not yet pin the source PR's current head."""
    recorded = json.loads(record_json).get("sha")
    if recorded != source_head:
        raise RuntimeError(
            f"{branch} pins backend-common {str(recorded)[:9]}, not the source head {source_head[:9]}; "
            "wait for Trigger Downstream to update it"
        )


def _gh(*args: str, check: bool = True, stdin: str | None = None) -> str:
    return subprocess.run(["gh", *args], capture_output=True, text=True, check=check, input=stdin, timeout=120).stdout


def _api(path: str, *fields: str, method: str = "GET") -> dict[str, object]:
    return json.loads(_gh("api", "-X", method, path, *fields) or "{}")


def _field(data: dict[str, object], *keys: str) -> str:
    value: object = data
    for key in keys:
        assert isinstance(value, dict), f"expected an object at {key!r}"
        value = value[key]
    return str(value)


def _seconds(start: object, end: object) -> float | None:
    if not isinstance(start, str) or not isinstance(end, str):
        return None
    return (dt.datetime.fromisoformat(end) - dt.datetime.fromisoformat(start)).total_seconds()


def _latest_runs(profile: ConsumerProfile, branch: str) -> list[dict[str, object]]:
    runs = _api(
        f"repos/{profile.repository}/actions/workflows/{profile.workflow}/runs"
        f"?branch={branch}&event=pull_request&per_page=20"
    )["workflow_runs"]
    assert isinstance(runs, list)
    return runs


T = TypeVar("T")


def _wait(condition: Callable[[], T | None], what: str) -> T:
    deadline = time.monotonic() + RUN_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        _pause(0)
        if (found := condition()) is not None:
            return found
        _pause(POLL_SECONDS)
    raise TimeoutError(f"timed out waiting for {what}")


def _next_run(profile: ConsumerProfile, session: DrillSession, known: set[int]) -> dict[str, object]:
    """Collect only a first-attempt run of this session's current immutable head, and mark it known."""
    head = session.head_sha

    def completed() -> list[dict[str, object]] | None:
        fresh = [
            run
            for run in _latest_runs(profile, session.branch)
            if run["id"] not in known
            and run.get("head_sha") == head
            and run.get("event") == "pull_request"
            and run.get("run_attempt") == 1
            and dt.datetime.fromisoformat(str(run["created_at"])) >= dt.datetime.fromisoformat(session.started_at)
        ]
        # Pick the earliest outstanding run, not whichever happened to finish last.
        fresh.sort(key=lambda run: int(str(run["id"])))
        # Two events at once create sibling runs, and concurrency cancels the older in favour of the newer:
        # follow the survivor. Only a cancelled run with no later sibling is measured, and so fails.
        pick = 0
        while pick < len(fresh) - 1 and fresh[pick]["conclusion"] == "cancelled":
            pick += 1
        return fresh[: pick + 1] if fresh and fresh[pick]["status"] == "completed" else None

    *casualties, run = _wait(completed, f"a new {profile.workflow} run at {head}")
    for casualty in casualties:
        _require_idle_casualty(profile, casualty, run)
    # Spend the casualties too, or one could stand in for the next scenario's run.
    known.update(int(str(each["id"])) for each in (*casualties, run))
    return run


def _jobs(profile: ConsumerProfile, run: dict[str, object]) -> list[dict[str, object]]:
    jobs = _api(f"repos/{profile.repository}/actions/runs/{run['id']}/jobs?filter=latest&per_page=100")["jobs"]
    assert isinstance(jobs, list)
    return jobs


def _require_idle_casualty(profile: ConsumerProfile, casualty: dict[str, object], survivor: dict[str, object]) -> None:
    """Skipping a casualty is sound only while it validated nothing: `score` never sees its repeats."""
    finished = [
        str(job["name"])
        for job in _jobs(profile, casualty)
        if job["conclusion"] in ("success", "failure") and not profile.always(str(job["name"]))
    ]
    if finished:
        raise RuntimeError(
            f"Run {casualty['id']} was cancelled in favour of {survivor['id']} after finishing "
            f"{', '.join(finished)}; the drill cannot score that repeated work"
        )
    print(
        f"{profile.repository}: run {casualty['id']} was cancelled in favour of sibling {survivor['id']} "
        "before validating anything; measuring the sibling",
        file=sys.stderr,
    )


def _outcome(profile: ConsumerProfile, label: str, run: dict[str, object]) -> RunOutcome:
    jobs = _jobs(profile, run)
    log = ""
    plan = next((job for job in jobs if job["name"] == profile.plan_job), None)
    if plan is None or plan["conclusion"] != "success":
        raise RuntimeError(f"Run {run['id']} did not successfully execute {profile.plan_job}")
    if plan is not None:
        log = _gh("run", "view", "-R", profile.repository, "--job", str(plan["id"]), "--log", check=False)
    lines = [match.group(1) for match in map(RESOLVER_LINES.search, log.splitlines()) if match]
    selection = parse_selection(log)
    if label in ("first run", "validated PR"):
        if selection is None or selection.selected == 0:
            raise RuntimeError(f"Initial run {run['id']} selected no tests or supplied no selection proof")
        if not any(
            fnmatch.fnmatchcase(str(job["name"]), profile.pytest_job) and job["conclusion"] not in (None, "skipped")
            for job in jobs
        ):
            raise RuntimeError(f"Initial run {run['id']} did not execute pytest")
    return RunOutcome(
        label=label,
        run_id=int(str(run["id"])),
        conclusion=None if run["conclusion"] is None else str(run["conclusion"]),
        wall_seconds=_seconds(run.get("run_started_at"), run.get("updated_at")),
        jobs=tuple(
            JobOutcome(
                name=str(job["name"]),
                conclusion=None if job["conclusion"] is None else str(job["conclusion"]),
                seconds=_seconds(job.get("started_at"), job.get("completed_at")),
            )
            for job in jobs
        ),
        resolver_lines=tuple(dict.fromkeys(lines)),
        selection=selection,
        plan_seconds=None if plan is None else _seconds(plan.get("started_at"), plan.get("completed_at")),
    )


def _branch_from(repository: str, source: str, branch: str) -> None:
    sha = _field(_api(f"repos/{repository}/git/ref/heads/{source}"), "object", "sha")
    _api(f"repos/{repository}/git/refs", "-f", f"ref=refs/heads/{branch}", "-f", f"sha={sha}", method="POST")


@contextmanager
def _frozen_main(profile: ConsumerProfile, branch: str) -> Iterator[str]:
    """Own a stable PR base until its drill completes, including error cleanup."""
    frozen = f"{branch}-base"
    _branch_from(profile.repository, "main", frozen)
    try:
        yield frozen
    finally:
        _gh("api", "-X", "DELETE", f"repos/{profile.repository}/git/refs/heads/{frozen}", check=False)


def _probe_commit(repository: str, branch: str, path: str) -> str:
    """Append an inert binding that survives AST-based impact filtering."""
    current = _api(f"repos/{repository}/contents/{path}?ref={branch}")
    text = base64.b64decode(_field(current, "content")).decode()
    touched = text + f'\n_CI_DRILL_PROBE = "{uuid.uuid4().hex}"  # Inert AST change; never merge.\n'
    body = {
        "message": f"ci-drill: inert AST probe in {path}",
        "content": base64.b64encode(touched.encode()).decode(),
        "sha": _field(current, "sha"),
        "branch": branch,
    }
    # On stdin: a whole module's base64 overflows one argument (Windows' command line, Linux's 128 KiB).
    commit = json.loads(
        _gh("api", "-X", "PUT", f"repos/{repository}/contents/{path}", "--input", "-", stdin=json.dumps(body))
    )
    return _field(commit, "commit", "sha")


def _open_drill_pr(profile: ConsumerProfile, base: str, branch: str, pr_base: str = "main") -> tuple[str, str]:
    _branch_from(profile.repository, pr_base if base == "main" else base, branch)
    head_sha = _probe_commit(profile.repository, branch, profile.touch_path)
    url = _gh(
        "pr", "create", "-R", profile.repository, "--draft", "--base", pr_base, "--head", branch,
        "--title", f"[ci-drill] DO NOT MERGE: {base}",
        "--body", "Throwaway PR opened by `scripts/ci/ci_drill.py` in backend-common. "
        "The drill closes it and deletes its branch when it ends.",
    ).strip()  # fmt: skip
    return url, head_sha


def _toggle_ready(url: str) -> None:
    _gh("pr", "ready", url, "--undo", check=False)
    _gh("pr", "ready", url)


ACTIONS: dict[str, Callable[[str], None]] = {"ready": _toggle_ready}


def drill_branch(profile: ConsumerProfile, base: str, now: dt.datetime, token: str) -> str:
    """Unique per drill: one consumer's main and bump-branch drills start in the same second."""
    slug = re.sub(r"[^0-9A-Za-z._-]+", "-", base)
    return f"ci-drill/{now:%Y%m%d-%H%M%S}-{profile.repository.rsplit('/', 1)[1]}-{slug}-{token}"


def readiness_triggers_validation(workflow: str) -> bool:
    """Read the candidate's actual trigger, including GitHub's implicit PR defaults."""
    events = yaml.load(workflow, Loader=yaml.BaseLoader).get("on", {})
    if not isinstance(events, dict):
        return False  # An unqualified pull_request uses opened/synchronize/reopened.
    pr = events.get("pull_request")
    return isinstance(pr, dict) and "ready_for_review" in pr.get("types", [])


def _assert_no_ready_run(profile: ConsumerProfile, session: DrillSession, known: set[int]) -> None:
    """Observe event delivery for 45s; any extra run is a failure, even if cancelled."""
    for _ in range(3):
        _pause(15)
        unexpected = [
            run
            for run in _latest_runs(profile, session.branch)
            if run["id"] not in known
            and run.get("head_sha") == session.head_sha
            and dt.datetime.fromisoformat(str(run["created_at"])) >= dt.datetime.fromisoformat(session.started_at)
        ]
        if unexpected:
            raise RuntimeError(f"Ready allocated unexpected runs: {[run['id'] for run in unexpected]}")


def drill(profile: ConsumerProfile, base: str, scenarios: Sequence[Scenario], fresh_pr: bool = False) -> Scorecard:
    with _drill_session(profile, base, "retrigger", fresh_pr) as session:
        known: set[int] = set()
        ready_runs = readiness_triggers_validation(
            _file_text(profile.repository, session.head_sha, f".github/workflows/{profile.workflow}")
        )
        if not ready_runs:

            def active() -> dict[str, object] | None:
                return next(
                    (
                        run
                        for run in _latest_runs(profile, session.branch)
                        if run.get("head_sha") == session.head_sha
                        and run.get("status") == "in_progress"
                        and dt.datetime.fromisoformat(str(run["created_at"]))
                        >= dt.datetime.fromisoformat(session.started_at)
                    ),
                    None,
                )

            initial = _wait(active, "validation in progress before Ready")
            ACTIONS["ready"](session.url)
            first = _next_run(profile, session, known)
            if first["id"] != initial["id"] or first["conclusion"] != "success":
                raise RuntimeError("Ready interrupted or replaced the active validation")
            _assert_no_ready_run(profile, session, known)
        else:
            first = _next_run(profile, session, known)
        runs = [_outcome(profile, "first run", first)]
        if not ready_runs:
            runs.append(
                RunOutcome(label="ready during active validation", run_id=None, jobs=(), wall_seconds=0, plan_seconds=0)
            )
        for scenario in scenarios:
            _pause(scenario.delay_seconds)
            ACTIONS[scenario.action](session.url)
            if ready_runs:
                run = _next_run(profile, session, known)
                runs.append(_outcome(profile, scenario.label, run))
            else:
                _assert_no_ready_run(profile, session, known)
                runs.append(RunOutcome(label=scenario.label, run_id=None, jobs=(), wall_seconds=0, plan_seconds=0))
            print(f"{profile.repository} {base}: {scenario.label} -> {runs[-1].run_id or 'no run'}", file=sys.stderr)
        return score(profile, base, session.head_sha, runs)


PIN = re.compile(r"backend-common\.git\?rev=([^\"#\s]+)#([0-9a-f]{40})")
PIN_FILES = ("uv.lock", "pyproject.toml", ".github/backend-common-bump.json")


def pinned(lock: str) -> tuple[str, str]:
    """The (rev, commit) a consumer lock pins backend-common at; exactly one must be pinned."""
    pins = set(PIN.findall(lock))
    if len(pins) != 1:
        raise ValueError(f"expected one backend-common pin in uv.lock, found {sorted(pins)}")
    return pins.pop()


def retag_pin(text: str, old: tuple[str, str], new: tuple[str, str]) -> str:
    """Move a pin from one (rev, commit) to another in a lock, manifest or bump record, as the automation does."""
    (old_rev, old_commit), (new_rev, new_commit) = old, new
    return (
        text.replace(f"backend-common.git?rev={old_rev}", f"backend-common.git?rev={new_rev}")
        .replace(f'rev = "{old_rev}"', f'rev = "{new_rev}"')
        .replace(old_commit, new_commit)
    )


def _file_text(repository: str, branch: str, path: str) -> str:
    return base64.b64decode(_field(_api(f"repos/{repository}/contents/{path}?ref={branch}"), "content")).decode()


def _api_json(path: str, body: dict[str, object], method: str = "POST") -> dict[str, object]:
    return json.loads(_gh("api", "-X", method, path, "--input", "-", stdin=json.dumps(body)) or "{}")


SlotCommits = tuple[str, str]


def _slot_snapshot(repository: str, main: str, source: str, old_head: str, old_base: str, nonce: str) -> SlotCommits:
    """Append a fresh evidence boundary, preserving source content and old ref ancestry."""
    root = f"repos/{repository}"
    main_tree = _field(_api(f"{root}/git/commits/{main}"), "tree", "sha")
    desired_tree = main_tree
    if source != main:
        # Compute content without slot ancestry: a previously drilled candidate is already
        # an ancestor of the slot base, but its changes still belong in this session.
        scratch = f"ci-drill/prepare/{nonce}"
        _api_json(f"{root}/git/refs", {"ref": f"refs/heads/{scratch}", "sha": main})
        try:
            _api_json(f"{root}/merges", {"base": scratch, "head": source})
            merged = _field(_api(f"{root}/git/ref/heads/{scratch}"), "object", "sha")
            desired_tree = _field(_api(f"{root}/git/commits/{merged}"), "tree", "sha")
        finally:
            _gh("api", "-X", "DELETE", f"{root}/git/refs/heads/{scratch}")
    base = _field(
        _api_json(
            f"{root}/git/commits",
            {
                "message": f"ci-drill session {nonce}: isolate previous evidence",
                "tree": main_tree,
                "parents": list(dict.fromkeys([main, old_head, old_base])),
            },
        ),
        "sha",
    )
    head = _field(
        _api_json(
            f"{root}/git/commits",
            {
                "message": f"ci-drill session {nonce}: source {source}",
                "tree": desired_tree,
                "parents": list(dict.fromkeys([base, source])),
            },
        ),
        "sha",
    )
    return base, head


# Existing throwaways adopted once; never silently create replacements for unavailable slots.
# Order: retrigger, retag, main-moved. One independent slot per consumer and comparison arm.
SLOT_PRS = {
    "gigaverse-app/gigaverse-backend": {"main": (5053, 5063, 5062), "candidate": (5059, 5061, 5064)},
    "gigaverse-app/gigaverse-ai": {"main": (2774, 2768, 2771), "candidate": (2775, 2772, 2773)},
}
SLOT_FAMILIES = ("retrigger", "retag", "main-moved")
LEASE_REF = "ci-drill/pool-lease"
#: Lease wait budget in minutes; the hosted workflow sets it (see --lease-wait-minutes).
LEASE_WAIT_ENV = "CI_DRILL_LEASE_WAIT_MINUTES"
STOP = threading.Event()


class DrillSession(DrillModel):
    url: str
    branch: str
    pr_base: str
    head_sha: str
    started_at: str


def _pause(seconds: float) -> None:
    if STOP.wait(seconds):
        raise RuntimeError("drill interrupted; cleaning up owned slots")


def _lease_holder(root: str) -> str | None:
    """The owner record of the current lease, or None when no lease ref exists."""
    try:
        sha = _field(_api(f"{root}/git/ref/heads/{LEASE_REF}"), "object", "sha")
    except subprocess.CalledProcessError:
        return None
    return _field(_api(f"{root}/git/commits/{sha}"), "message").partition("\n")[2].strip()


@contextmanager
def _pool_lease(wait_seconds: float = 0) -> Iterator[None]:
    """
    Atomic cross-host exclusion. A killed owner leaves a visible, fail-closed lease.

    The hosted job's concurrency group queues only hosted drills; a local CLI driver
    holds this lease instead, so a driver may wait up to ``wait_seconds`` for the
    holder to release it. Waiting never takes a lease over: acquisition is still the
    atomic ref creation, which succeeds only after the holder deletes its ref.
    """
    root = f"repos/{SOURCE_REPOSITORY}"
    main = _field(_api(f"{root}/git/ref/heads/main"), "object", "sha")
    tree = _field(_api(f"{root}/git/commits/{main}"), "tree", "sha")
    owner = json.dumps(
        {
            "session": uuid.uuid4().hex,
            "host": socket.gethostname(),
            "pid": os.getpid(),
            "run": os.environ.get("GITHUB_RUN_ID"),
            "repository": os.environ.get("GITHUB_REPOSITORY"),
            "started_at": dt.datetime.now(dt.UTC).isoformat(),
        }
    )
    sha = _field(
        _api_json(
            f"{root}/git/commits",
            {
                "message": f"ci-drill pool lease\n{owner}",
                "tree": tree,
                "parents": [main],
            },
        ),
        "sha",
    )
    deadline = time.monotonic() + wait_seconds
    reported: str | None = None
    while True:
        try:
            _api_json(f"{root}/git/refs", {"ref": f"refs/heads/{LEASE_REF}", "sha": sha})
            break
        except subprocess.CalledProcessError as error:
            # Only a visible lease is contention; any other refusal (auth, transport) is not worth waiting out.
            holder = _lease_holder(root)
            if holder is None:
                raise
            if time.monotonic() >= deadline:
                raise RuntimeError(
                    f"Cannot acquire {SOURCE_REPOSITORY}:{LEASE_REF}; held by {holder}. "
                    "Inspect the lease commit; recover only after proving its owner has stopped."
                ) from error
            if holder != reported:  # once per holder, not once per poll
                print(f"Waiting for {LEASE_REF}, held by {holder}", file=sys.stderr)
                reported = holder
            _pause(POLL_SECONDS)
    try:
        yield
    finally:
        current = _field(_api(f"{root}/git/ref/heads/{LEASE_REF}"), "object", "sha")
        if current != sha:
            raise RuntimeError("Pool lease ownership changed; refusing to delete another owner's lease")
        _gh("api", "-X", "DELETE", f"{root}/git/refs/heads/{LEASE_REF}")


def _ref_or_recorded(repository: str, branch: str, recorded: str) -> str:
    """A closed PR can lag a ref advanced by an interrupted preparation."""
    try:
        return _field(_api(f"repos/{repository}/git/ref/heads/{branch}"), "object", "sha")
    except subprocess.CalledProcessError as error:
        if "HTTP 404" not in str(error.stderr):
            raise
        return recorded


def _slot_ref(repository: str, branch: str, sha: str) -> None:
    """Restore a deleted drill ref or advance it; GitHub rejects non-fast-forward updates."""
    root = f"repos/{repository}/git"
    try:
        _api_json(f"{root}/refs/heads/{branch}", {"sha": sha, "force": False}, method="PATCH")
    except subprocess.CalledProcessError:
        # Creation is also conditional: it cannot overwrite a ref or hide a failed FF check.
        _api_json(f"{root}/refs", {"ref": f"refs/heads/{branch}", "sha": sha})


def _close_slot(profile: ConsumerProfile, session: DrillSession) -> None:
    # Cancel unfinished runs before making the slot available to a subsequent driver.
    for run in _latest_runs(profile, session.branch):
        if run["status"] != "completed":
            _gh("run", "cancel", str(run["id"]), "-R", profile.repository, check=False)
    state = json.loads(_gh("pr", "view", session.url, "--json", "isDraft,state"))
    if state["state"] == "OPEN":
        if not state["isDraft"]:
            _gh("pr", "ready", session.url, "--undo")
    else:
        return
    _gh("pr", "close", session.url)


@contextmanager
def _drill_session(profile: ConsumerProfile, base: str, family: str, fresh_pr: bool) -> Iterator[DrillSession]:
    _pause(0)
    started_at = dt.datetime.now(dt.UTC).isoformat()
    if fresh_pr:
        branch = drill_branch(profile, f"{base}-{family}", dt.datetime.now(dt.UTC), uuid.uuid4().hex[:8])
        with _frozen_main(profile, branch) as pr_base:
            url, head_sha = _open_drill_pr(profile, base, branch, pr_base)
            try:
                yield DrillSession(url=url, branch=branch, pr_base=pr_base, head_sha=head_sha, started_at=started_at)
            finally:
                _gh("pr", "close", url, "--delete-branch")
        return
    number = SLOT_PRS[profile.repository]["main" if base == "main" else "candidate"][SLOT_FAMILIES.index(family)]
    root = f"repos/{profile.repository}"
    pr = _api(f"{root}/pulls/{number}")
    branch, pr_base = _field(pr, "head", "ref"), _field(pr, "base", "ref")
    if (
        pr["state"] != "closed"
        or pr["merged"]
        or not branch.startswith("ci-drill/")
        or (pr_base != "main" and not pr_base.startswith("ci-drill/"))
        or _field(pr, "head", "repo", "full_name") != profile.repository
        or _field(pr, "base", "repo", "full_name") != profile.repository
        or "scripts/ci/ci_drill.py" not in str(pr["body"])
    ):
        raise RuntimeError(f"Refusing to adopt {profile.repository}#{number}: not an idle, owned drill PR")
    if any(run["status"] != "completed" for run in _latest_runs(profile, branch)):
        raise RuntimeError(f"Slot #{number} still has active runs; wait or recover the interrupted session")
    main = _field(_api(f"{root}/git/ref/heads/main"), "object", "sha")
    source = main if base == "main" else _field(_api(f"{root}/git/ref/heads/{base}"), "object", "sha")
    base_sha, head_sha = _slot_snapshot(
        profile.repository,
        main,
        source,
        _ref_or_recorded(profile.repository, branch, _field(pr, "head", "sha")),
        _ref_or_recorded(profile.repository, pr_base, _field(pr, "base", "sha")),
        uuid.uuid4().hex,
    )
    # Restore the old base before reopening. GitHub keeps a closed PR's recorded head:
    # absorbing it into the base while closed makes that PR permanently un-reopenable.
    try:
        _api(f"{root}/git/ref/heads/{pr_base}")
    except subprocess.CalledProcessError:
        if pr_base == "main":
            raise
        _api_json(f"{root}/git/refs", {"ref": f"refs/heads/{pr_base}", "sha": _field(pr, "base", "sha")})
    _slot_ref(profile.repository, branch, head_sha)
    session = DrillSession(
        url=_field(pr, "html_url"), branch=branch, pr_base=pr_base, head_sha=head_sha, started_at=started_at
    )
    try:
        _gh("pr", "reopen", session.url)
        if not pr["draft"]:
            _gh("pr", "ready", session.url, "--undo")
        next_base = f"{branch}-pool-{'b' if pr_base.endswith('-pool-a') else 'a'}"
        _slot_ref(profile.repository, next_base, base_sha)
        changed = _api_json(f"{root}/pulls/{number}", {"base": next_base}, method="PATCH")
        if _field(changed, "base", "sha") != base_sha:
            raise RuntimeError("GitHub did not adopt the session base; refusing to collect stale evidence")
        session = session.model_copy(update={"pr_base": next_base})
        head_sha = _probe_commit(profile.repository, branch, profile.touch_path)
        session = session.model_copy(update={"head_sha": head_sha})
        _api_json(
            f"{root}/pulls/{number}",
            {
                "title": f"[ci-drill slot] {family}: {'main' if base == 'main' else 'candidate'} — DO NOT MERGE",
                "body": "Reusable slot owned by `scripts/ci/ci_drill.py` in backend-common. "
                f"Do not merge or delete its refs. Current source: `{base}` (`{source}`). "
                f"Session head: `{head_sha}`. Closed when idle; history is reused.",
            },
            method="PATCH",
        )
        print(f"{profile.repository} {base} {family}: reused {session.url} at {head_sha}", file=sys.stderr)
        yield session
    finally:
        _close_slot(profile, session)


def _identical_tree_tag(commit: str, tag: str) -> str:
    """A new backend-common commit of `commit`'s tree, tagged `tag`: what merging the source PR produces."""
    tree = _field(_api(f"repos/{SOURCE_REPOSITORY}/git/commits/{commit}"), "tree", "sha")
    retagged = _api_json(
        f"repos/{SOURCE_REPOSITORY}/git/commits",
        {"message": f"ci-drill: {commit[:9]}'s tree under a new commit", "tree": tree, "parents": [commit]},
    )
    new_commit = _field(retagged, "sha")
    _api_json(f"repos/{SOURCE_REPOSITORY}/git/refs", {"ref": f"refs/tags/{tag}", "sha": new_commit})
    return new_commit


def _retag_branch(repository: str, branch: str, tag: str) -> str:
    """One commit moving the branch's pin to `tag`, rewriting exactly the files the automation owns."""
    lock = _file_text(repository, branch, "uv.lock")
    old = pinned(lock)
    new = (tag, _identical_tree_tag(old[1], tag))
    head = _field(_api(f"repos/{repository}/git/ref/heads/{branch}"), "object", "sha")
    base_tree = _field(_api(f"repos/{repository}/git/commits/{head}"), "tree", "sha")
    entries = [
        {
            "path": path,
            "mode": "100644",
            "type": "blob",
            "content": retag_pin(_file_text(repository, branch, path), old, new),
        }
        for path in PIN_FILES
    ]
    tree = _field(_api_json(f"repos/{repository}/git/trees", {"base_tree": base_tree, "tree": entries}), "sha")
    commit = _field(
        _api_json(
            f"repos/{repository}/git/commits",
            {"message": f"ci-drill: retag backend-common to {tag} (identical tree)", "tree": tree, "parents": [head]},
        ),
        "sha",
    )
    _api_json(f"repos/{repository}/git/refs/heads/{branch}", {"sha": commit}, method="PATCH")
    return commit


def drill_retag(profile: ConsumerProfile, base: str, fresh_pr: bool = False) -> Scorecard:
    """Validate a ready PR, then retag its pin to an identical backend-common tree."""
    tag = f"ci-drill-retag-{uuid.uuid4().hex}"
    with _drill_session(profile, base, "retag", fresh_pr) as session:
        try:
            known: set[int] = set()
            runs: list[RunOutcome] = []
            for label, act in (("first run", None), ("ready", _toggle_ready), (RETAG_LABEL, None)):
                _pause(0)
                if act is not None:
                    act(session.url)
                    if not readiness_triggers_validation(
                        _file_text(profile.repository, session.head_sha, f".github/workflows/{profile.workflow}")
                    ):
                        _assert_no_ready_run(profile, session, known)
                        runs.append(RunOutcome(label=label, run_id=None, jobs=(), wall_seconds=0, plan_seconds=0))
                        continue
                if label == RETAG_LABEL:
                    retagged_head = _retag_branch(profile.repository, session.branch, tag)
                    session = session.model_copy(update={"head_sha": retagged_head})
                run = _next_run(profile, session, known)
                runs.append(_outcome(profile, label, run))
                print(f"{profile.repository} {base}: {label} -> run {run['id']} {run['conclusion']}", file=sys.stderr)
            return score(profile, base, session.head_sha, runs, family="retag")
        finally:
            _gh("api", "-X", "DELETE", f"repos/{SOURCE_REPOSITORY}/git/refs/tags/{tag}", check=False)


def drill_main_moved(profile: ConsumerProfile, base: str, fresh_pr: bool = False) -> MainMovedCard:
    """Move a drill-owned base, merge it, and measure selection without touching real main."""
    with _drill_session(profile, base, "main-moved", fresh_pr) as session:
        known: set[int] = set()
        first = _next_run(profile, session, known)
        runs = [_outcome(profile, "validated PR", first)]
        _pause(0)
        _probe_commit(profile.repository, session.pr_base, profile.broad_path)
        merged = _api_json(
            f"repos/{profile.repository}/merges",
            {
                "base": session.branch,
                "head": session.pr_base,
                "commit_message": f"Merge {session.pr_base} into {session.branch} (ci-drill: main moved)",
            },
        )
        session = session.model_copy(update={"head_sha": _field(merged, "sha")})
        after = _next_run(profile, session, known)
        runs.append(_outcome(profile, "after main moved", after))
        print(f"{profile.repository} {base}: main moved -> run {after['id']} {after['conclusion']}", file=sys.stderr)
        return MainMovedCard(consumer=profile.repository, base=base, runs=tuple(runs))


def _source_head(source_pr: int) -> str:
    return _gh(
        "pr", "view", str(source_pr), "-R", SOURCE_REPOSITORY, "--json", "headRefOid", "-q", ".headRefOid"
    ).strip()


def _wait_for_bump_branches(consumers: Sequence[str], source_pr: int, source_head: str) -> None:
    """Trigger Downstream updates the bump branches after a push; drill only once they pin this head."""
    branch = bump_branch(source_pr)
    deadline = time.monotonic() + RUN_TIMEOUT_SECONDS
    for consumer in consumers:
        path = f"repos/{PROFILES[consumer].repository}/contents/.github/backend-common-bump.json?ref={branch}"
        while True:
            try:
                require_current_bump(base64.b64decode(_field(_api(path), "content")).decode(), source_head, branch)
                break
            except (RuntimeError, subprocess.CalledProcessError) as error:
                if time.monotonic() > deadline:
                    raise RuntimeError(f"{PROFILES[consumer].repository}: {error}") from error
                _pause(POLL_SECONDS)


def report(
    source_pr: int | None,
    cards: Sequence[Scorecard],
    comparisons: Sequence[Comparison],
    failures: Sequence[DrillFailure] = (),
    moved: Sequence[MainMovedCard] = (),
    moved_comparisons: Sequence[MainMovedComparison] = (),
) -> str:
    lines = ["### CI drill" + (f" for backend-common#{source_pr}" if source_pr else ""), ""]
    for failure in failures:
        lines += [f"**Drill error**, {failure.consumer} from `{failure.base}`: {failure.error}", ""]
    if comparisons or moved_comparisons:
        lines += ["| Consumer | Drill | Against main | Why |", "|---|---|---|---|"]
        lines += [
            f"| {item.candidate.consumer} | {item.candidate.family.replace('retrigger', 're-trigger')} "
            f"| **{item.verdict}** | {'; '.join(item.reasons)} |"
            for item in comparisons
        ]
        lines += [
            f"| {item.candidate.consumer} | main moved | **{item.verdict}** | {'; '.join(item.reasons)} |"
            for item in moved_comparisons
        ]
        lines.append("")
    for card in [*cards, *moved]:
        lines += [card.markdown(), ""]
    lines.append(
        "_Posted by `scripts/ci/ci_drill.py`; live GitHub results; drill errors mean the affected scenario was not proven._"
    )
    return "\n".join(lines)


def met(
    expect: str,
    cards: Sequence[Scorecard],
    comparisons: Sequence[Comparison],
    failures: Sequence[DrillFailure] = (),
    moved: Sequence[MainMovedCard] = (),
    moved_comparisons: Sequence[MainMovedComparison] = (),
) -> bool:
    """
    ``pass``: every candidate is green and nothing regressed against main.

    ``improved`` also needs each drilled consumer to improve in at least one drill: a change
    aimed at selection leaves re-triggers unchanged and one aimed at reuse leaves selection
    unchanged, but neither may regress the other.
    """
    if failures:
        return False
    candidates = [card for card in cards if card.base != "main"] or list(cards)
    verdicts = [(item.candidate.consumer, item.verdict) for item in [*comparisons, *moved_comparisons]]
    moved_candidates = [card for card in moved if card.base != "main"] or list(moved)
    green = all(card.passed for card in candidates) and not any(card.red_runs for card in moved_candidates)
    if not green or any(verdict == "regressed" for _, verdict in verdicts):
        return False
    if expect == "improved":
        consumers = {consumer for consumer, _ in verdicts}
        return bool(consumers) and all(
            any(verdict == "improved" for name, verdict in verdicts if name == consumer) for consumer in consumers
        )
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Prove a CI change on real GitHub before it merges.")
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--source-pr", type=int, help="backend-common PR whose generated bump branches to drill")
    target.add_argument("--base", help="drill this consumer branch directly (e.g. main)")
    parser.add_argument("--consumer", choices=[*sorted(PROFILES), "all"], default="all")
    parser.add_argument("--scenario", choices=sorted(SCENARIOS), action="append", help="default: all scenarios")
    parser.add_argument(
        "--drill", choices=["retrigger", "main-moved", "retag"], action="append", dest="families", help="default: all"
    )
    parser.add_argument("--compare-main", action="store_true", help="drill each consumer's main side by side")
    parser.add_argument("--thorough", action="store_true", help="also run the slow scenarios (listing lag)")
    parser.add_argument("--expect", choices=["pass", "improved"], default="pass")
    parser.add_argument("--post", action="store_true", help="comment and set the ci-drill status on the source PR")
    parser.add_argument("--fresh-pr", action="store_true", help="explicitly create throwaways to test opened events")
    parser.add_argument(
        "--lease-wait-minutes",
        type=float,
        # The hosted workflow sets the budget through the environment, not argv: it runs the
        # default branch's script with a PR's workflow, and an older script rejects unknown flags.
        default=float(os.environ.get(LEASE_WAIT_ENV, "0")),
        help=f"wait this long for another driver to release the pool lease (default: ${LEASE_WAIT_ENV} or 0)",
    )
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    STOP.clear()
    signal.signal(signal.SIGTERM, lambda *_: STOP.set())
    signal.signal(signal.SIGINT, lambda *_: STOP.set())

    consumers = sorted(PROFILES) if args.consumer == "all" else [args.consumer]
    default_scenarios = [key for key, scenario in SCENARIOS.items() if args.thorough or not scenario.thorough]
    scenarios = [SCENARIOS[key] for key in (args.scenario or default_scenarios)]
    source_head = ""
    if args.source_pr:
        source_head = _source_head(args.source_pr)
        _wait_for_bump_branches(consumers, args.source_pr, source_head)
    base = bump_branch(args.source_pr) if args.source_pr else args.base
    families = list(dict.fromkeys(args.families or SLOT_FAMILIES))
    targets = [(consumer, base) for consumer in consumers]
    if args.compare_main:
        targets += [(consumer, "main") for consumer in consumers if base != "main"]
    runners: dict[str, Callable[[ConsumerProfile, str], Scorecard | MainMovedCard]] = {
        "retrigger": lambda profile, job_base: drill(profile, job_base, scenarios, args.fresh_pr),
        "main-moved": lambda profile, job_base: drill_main_moved(profile, job_base, args.fresh_pr),
        "retag": lambda profile, job_base: drill_retag(profile, job_base, args.fresh_pr),
    }
    jobs = [(family, consumer, job_base) for family in families for consumer, job_base in targets]
    cards: list[Scorecard] = []
    moved: list[MainMovedCard] = []
    failures: list[DrillFailure] = []
    lease = nullcontext() if args.fresh_pr else _pool_lease(args.lease_wait_minutes * 60)
    with lease, concurrent.futures.ThreadPoolExecutor(len(jobs)) as pool:
        futures = {
            pool.submit(runners[family], PROFILES[consumer], job_base): (family, consumer, job_base)
            for family, consumer, job_base in jobs
        }
        for future in concurrent.futures.as_completed(futures):
            family, consumer, job_base = futures[future]
            try:
                result = future.result()
            except Exception as error:  # noqa: BLE001 - reported as a drill failure, never swallowed
                failures.append(
                    DrillFailure(
                        consumer=PROFILES[consumer].repository, base=f"{job_base} ({family})", error=repr(error)
                    )
                )
                continue
            if isinstance(result, MainMovedCard):
                moved.append(result)
            else:
                cards.append(result)
    comparisons = [
        compare(baseline, candidate)
        for candidate in cards
        if candidate.base != "main"
        for baseline in cards
        if baseline.base == "main" and baseline.consumer == candidate.consumer and baseline.family == candidate.family
    ]
    moved_comparisons = [
        compare_main_moved(baseline, candidate)
        for candidate in moved
        if candidate.base != "main"
        for baseline in moved
        if baseline.base == "main" and baseline.consumer == candidate.consumer
    ]
    ok = met(args.expect, cards, comparisons, failures, moved, moved_comparisons)
    text = report(args.source_pr, cards, comparisons, failures, moved, moved_comparisons)
    if args.post and args.source_pr:
        _gh("pr", "comment", str(args.source_pr), "-R", SOURCE_REPOSITORY, "--body-file", "-", stdin=text)
        _api(
            f"repos/{SOURCE_REPOSITORY}/statuses/{source_head}",
            "-f", f"state={'success' if ok else 'failure'}", "-f", f"context={STATUS_CONTEXT}",
            "-f", f"description=CI drill {'met' if ok else 'did not meet'} --expect {args.expect}",
            method="POST",
        )  # fmt: skip
    print(json.dumps([card.model_dump() for card in [*cards, *moved]], indent=1) if args.json else text)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
