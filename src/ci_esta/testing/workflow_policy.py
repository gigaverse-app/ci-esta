"""
Repository-wide invariants about GitHub workflow *definitions*.

Each invariant here reads every workflow file in a repository's
``.github/workflows`` and reports the ones that violate it, so a consumer's
test suite pins the property for the whole directory rather than for a
hand-maintained list of file names. That distinction is the point: a list of
names rots silently the moment a workflow is renamed, folded into another one,
or added. gigaverse-backend's first version of the stacked-PR check named
``test.yaml`` and ``typecheck.yaml`` explicitly; when ``typecheck.yaml`` was
folded into ``test.yaml`` and reduced to ``workflow_dispatch``, the check
stopped asserting anything and started raising ``KeyError`` instead.

Base-branch independence
------------------------
``on.pull_request.branches`` is a filter on the pull request's **base**
branch, not its head. A workflow that declares ``branches: [main]`` therefore
runs for a PR into ``main`` and is skipped entirely for a stacked PR whose base
is another feature branch — the PR reports no checks at all, which reads as
"nothing to run" rather than "not evaluated". Stacked PRs are how large changes
get reviewed here, so validation must not depend on what a PR is based on.

``branches-ignore`` fails the same way from the other side, and
``pull_request_target`` carries the identical filter semantics, so all four
combinations are in scope.

The matching ``push`` trigger is *not* in scope: there the filter selects which
protected branch was pushed, which is exactly what it should do.

Yielding to cancellation
------------------------
GitHub re-evaluates a job's ``if`` when the run is cancelled and lets the job
start or keep running while that condition is still true. ``always()`` is
unconditionally true, so a job guarded by it ignores ``cancel-in-progress``: it
runs to completion, holds the workflow's concurrency group, and the superseding
run waits behind it with none of its required checks reported. ``!cancelled()``
keeps the "run even after a failed or skipped prerequisite" behaviour that
nearly every ``always()`` job actually wants, without the immunity.

Measured on gigaverse-backend#4926: a superseded shard job *started* one second
after four sibling jobs of the same run had already been cancelled, then ran to
``success`` for another 4m39s, and two supersessions added 8m29s of pure queue
delay. The same job on the same runner pool, switched to ``!cancelled()`` and
superseded again, ended as ``cancelled`` after 1m09s.

Scope is asked per job, because a job can be cancellable when its workflow is
not: a workflow whose runs can be cancelled, a reusable workflow that inherits
a cancelling caller, and any job carrying its own cancelling ``concurrency:``
block. A workflow that can never cancel a run cannot strand anything, which is
why a deploy pipeline's ``always()`` summary job stays legal.
"""

from __future__ import annotations

import re
from collections.abc import Collection, Iterable
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict

WORKFLOW_SUFFIXES = (".yml", ".yaml")

# Both events apply `branches` to the pull request's base branch.
PULL_REQUEST_EVENTS = ("pull_request", "pull_request_target")

# `branches` keeps only the listed bases; `branches-ignore` drops them. Either
# way the trigger depends on what the PR is based on.
BASE_BRANCH_FILTER_KEYS = ("branches", "branches-ignore")

# A parsed workflow's keys are not all `str`: YAML 1.1 reads the unquoted `on`
# trigger key as the boolean True, so the mapping is genuinely object-keyed.
WorkflowDocument = dict[object, object]


class BaseBranchFilteredTrigger(BaseModel):
    """One pull-request trigger that a stacked PR's base branch can switch off."""

    model_config = ConfigDict(frozen=True)

    workflow: str
    event: str
    filter_key: str
    patterns: tuple[str, ...]

    @property
    def key(self) -> str:
        """The ``<workflow file>:<event>`` spelling used to allow a trigger explicitly."""
        return f"{self.workflow}:{self.event}"


def _triggers(document: WorkflowDocument) -> object:
    # `on` is a YAML 1.1 boolean, so safe_load yields the key True. Both
    # spellings appear in the wild depending on quoting.
    if "on" in document:
        return document["on"]
    return document.get(True)


def iter_workflow_files(workflow_dir: Path) -> list[Path]:
    """Every workflow definition directly inside ``workflow_dir``, in a stable order."""
    return sorted(
        path
        for path in workflow_dir.glob("*")
        # `is_file()` because a *directory* named `foo.yaml` matches the suffix
        # test and then raises on read.
        if path.suffix in WORKFLOW_SUFFIXES and path.is_file()
    )


def require_workflow_files(workflow_dir: Path) -> list[Path]:
    """
    Every workflow in ``workflow_dir``, refusing to report success on nothing.

    A directory-wide invariant is vacuously true over an empty directory, so a
    mistyped path (``.github/workflow``) or a call from the wrong repository
    root makes the assertion pass forever while checking nothing -- the exact
    silent-green failure these invariants exist to catch. Every assertion in
    this module goes through here so that mistake fails loudly and immediately.
    """
    workflows = iter_workflow_files(workflow_dir)
    if not workflows:
        raise AssertionError(
            f"No workflow files found under {workflow_dir}. A directory invariant over an empty "
            "directory passes without checking anything, so this is reported as a failure: fix the "
            "path the test passes in rather than the workflows."
        )
    return workflows


def _base_branch_filters(triggers: object) -> Iterable[tuple[str, str, tuple[str, ...]]]:
    """Every ``(event, filter key, patterns)`` a mapping-form trigger block declares."""
    # `on: pull_request` and `on: [push, pull_request]` cannot carry a filter at
    # all, so only the mapping form can violate the invariant.
    if not isinstance(triggers, dict):
        return
    for event in PULL_REQUEST_EVENTS:
        configuration = triggers.get(event)
        if not isinstance(configuration, dict):
            continue
        for filter_key in BASE_BRANCH_FILTER_KEYS:
            patterns = configuration.get(filter_key)
            if patterns is None:
                continue
            listed = patterns if isinstance(patterns, list) else [patterns]
            yield event, filter_key, tuple(str(pattern) for pattern in listed)


def find_base_branch_filtered_triggers(workflow_dir: Path) -> list[BaseBranchFilteredTrigger]:
    """Every pull-request trigger in ``workflow_dir`` that filters on the base branch."""
    filtered: list[BaseBranchFilteredTrigger] = []
    for path in require_workflow_files(workflow_dir):
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(document, dict):
            continue
        for event, filter_key, patterns in _base_branch_filters(_triggers(document)):
            filtered.append(
                BaseBranchFilteredTrigger(
                    workflow=path.name,
                    event=event,
                    filter_key=filter_key,
                    patterns=patterns,
                )
            )
    return filtered


def assert_pr_triggers_ignore_base_branch(
    workflow_dir: Path,
    *,
    allow: Collection[str] = (),
) -> None:
    """
    Fail when a pull-request trigger only fires for certain base branches.

    ``allow`` holds ``"<workflow file>:<event>"`` entries for triggers that
    genuinely belong to one base branch — a workflow that acts on a merge into
    a protected branch, say. Each entry silently exempts every stacked PR from
    that workflow, so it needs a stated reason at the call site.
    """
    offenders = [trigger for trigger in find_base_branch_filtered_triggers(workflow_dir) if trigger.key not in allow]
    if not offenders:
        return
    detail = "\n".join(f"  {trigger.key}\n    {trigger.filter_key}: {list(trigger.patterns)}" for trigger in offenders)
    raise AssertionError(
        "These pull-request triggers filter on the PR's base branch, so a stacked PR based on "
        "another feature branch never runs them and reports no check at all:\n"
        f"{detail}\n"
        "Delete the branch filter from the pull_request trigger; the push trigger's own filter "
        "already scopes protected-branch runs."
    )


# Match the calls, not one conventional spelling. GitHub's expression functions
# are case-insensitive, whitespace inside a call is legal, and the negation is
# written both `!cancelled()` and `!(cancelled())`. Missing any of those would
# either wave a real offender through or reject correct code.
_ALWAYS = re.compile(r"\balways\s*\(\s*\)", re.IGNORECASE)
_NOT_CANCELLED = re.compile(r"!\s*\(?\s*cancelled\s*\(\s*\)", re.IGNORECASE)


class CancelImmuneJob(BaseModel):
    """One job whose condition survives the cancellation of its own run."""

    model_config = ConfigDict(frozen=True)

    workflow: str
    job_id: str
    condition: str

    @property
    def key(self) -> str:
        """The ``<workflow file>:<job id>`` spelling used to allow a job explicitly."""
        return f"{self.workflow}:{self.job_id}"


def job_is_cancel_immune(condition: str | None) -> bool:
    """True when ``condition`` forces the job to run even after its run is cancelled."""
    if not condition:
        return False
    text = " ".join(str(condition).split())
    return bool(_ALWAYS.search(text)) and not _NOT_CANCELLED.search(text)


def _concurrency_cancels(concurrency: object) -> bool:
    """True when a ``concurrency:`` block can cancel whatever it governs."""
    if isinstance(concurrency, dict):
        cancel = concurrency.get("cancel-in-progress", False)
    else:
        # `concurrency: <group>` is the group-only shorthand; it queues, never cancels.
        cancel = False
    if isinstance(cancel, str):
        # An expression is only known at run time, so treat anything that is not
        # a literal false as able to cancel.
        return cancel.strip().lower() not in {"", "false"}
    return bool(cancel)


def workflow_can_cancel(document: WorkflowDocument) -> bool:
    """True when a run of this workflow can be cancelled by a newer one."""
    return _concurrency_cancels(document.get("concurrency"))


def job_can_cancel(job: dict[object, object]) -> bool:
    """
    True when this job's own concurrency group can cancel it.

    A job may carry a ``concurrency:`` block even when its workflow carries
    none, so this has to be asked per job rather than inferred from the
    workflow. Three workflows across these repositories have that shape today.
    """
    return _concurrency_cancels(job.get("concurrency"))


def workflow_is_reusable(document: WorkflowDocument) -> bool:
    """True when the workflow is called by another and inherits its concurrency group."""
    triggers = _triggers(document)
    if isinstance(triggers, str):
        return triggers == "workflow_call"
    if isinstance(triggers, dict | list):
        return "workflow_call" in triggers
    return False


def local_reusable_callees(document: WorkflowDocument) -> set[str]:
    """File names of workflows in the same directory that this one calls."""
    jobs = document.get("jobs")
    if not isinstance(jobs, dict):
        return set()
    callees: set[str] = set()
    for job in jobs.values():
        uses = job.get("uses") if isinstance(job, dict) else None
        if isinstance(uses, str) and uses.startswith("./.github/workflows/"):
            callees.add(uses.split("/")[-1].split("@")[0])
    return callees


def workflows_in_scope(documents: dict[str, WorkflowDocument]) -> set[str]:
    """
    The workflows whose jobs a cancellation could strand.

    A workflow that cancels its own runs is in scope directly. A reusable
    workflow has no concurrency of its own, so it inherits the question from
    whoever calls it: in scope when a caller in this directory is, and out of
    scope when every local caller never cancels. That last case is real and
    worth the graph walk, because a deploy pipeline deliberately has no
    cancellation and its called stages legitimately use ``always()``. A
    reusable workflow with no local caller is assumed to be called from another
    repository, which is what reusable workflows published for consumers are
    for, so it stays in scope.
    """
    in_scope = {name for name, document in documents.items() if workflow_can_cancel(document)}
    callers: dict[str, set[str]] = {}
    for name, document in documents.items():
        for callee in local_reusable_callees(document):
            callers.setdefault(callee, set()).add(name)
    in_scope |= {name for name, document in documents.items() if workflow_is_reusable(document) and name not in callers}
    # A callee inherits scope from any caller, and a caller may itself be a
    # callee, so propagate until the set stops growing.
    while True:
        inherited = {callee for callee, names in callers.items() if names & in_scope}
        if inherited <= in_scope:
            return in_scope
        in_scope |= inherited


def load_workflows(workflow_dir: Path) -> dict[str, WorkflowDocument]:
    """Every parsed workflow mapping in ``workflow_dir``, keyed by file name."""
    documents: dict[str, WorkflowDocument] = {}
    for path in require_workflow_files(workflow_dir):
        try:
            document = yaml.safe_load(path.read_text(encoding="utf-8"))
        except yaml.YAMLError as error:
            raise ValueError(f"{path.name}: cannot parse workflow: {error}") from error
        if isinstance(document, dict):
            documents[path.name] = document
    return documents


def find_cancel_immune_jobs(workflow_dir: Path) -> list[CancelImmuneJob]:
    """Every job in ``workflow_dir`` whose condition would survive its run being cancelled."""
    documents = load_workflows(workflow_dir)
    in_scope = workflows_in_scope(documents)
    immune: list[CancelImmuneJob] = []
    for name in sorted(documents):
        jobs = documents[name].get("jobs")
        if not isinstance(jobs, dict):
            continue
        for job_id, job in jobs.items():
            if not isinstance(job, dict):
                continue
            if name not in in_scope and not job_can_cancel(job):
                continue
            condition = job.get("if")
            if job_is_cancel_immune(condition if isinstance(condition, str) else None):
                immune.append(
                    CancelImmuneJob(
                        workflow=name,
                        job_id=str(job_id),
                        condition=" ".join(str(condition).split()),
                    )
                )
    return immune


def assert_no_cancel_immune_jobs(workflow_dir: Path, *, allow: Collection[str] = ()) -> None:
    """
    Fail when a job that a cancellation should reach ignores it.

    ``allow`` holds ``"<workflow file>:<job id>"`` entries for jobs that must
    genuinely outlive a cancelled run. Each one keeps a superseding run queued
    for that job's full duration, so it needs a stated reason at the call site.
    """
    immune = find_cancel_immune_jobs(workflow_dir)
    offenders = [job for job in immune if job.key not in allow]
    if not offenders:
        stale = sorted(set(allow) - {job.key for job in immune})
        if stale:
            raise AssertionError(
                "These allow entries no longer match a cancel-immune job and should be removed: " + ", ".join(stale)
            )
        return
    detail = "\n".join(f"  {job.key}\n    if: {job.condition}" for job in offenders)
    raise AssertionError(
        "These jobs ignore cancel-in-progress, so a superseded run keeps them running and "
        "holds its concurrency group while the replacement run waits:\n"
        f"{detail}\n"
        "Replace always() with !cancelled() to keep the run-after-failed-or-skipped-prerequisite "
        "behaviour without the immunity."
    )
