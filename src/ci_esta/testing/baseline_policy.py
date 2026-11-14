"""Own baseline identity and its complete change evidence across selection adapters.

A fork point describes PR edits; it is never a receipt of tested work. Exact
validated trees preserve imported changes and conflict resolutions. A synthetic
merge has a different proof: its recorded PR head must be its second parent.
Remote receipt ownership/completion is admitted upstream, not inferred here.
"""

import subprocess
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from ci_esta.git import git


class BaselineKind(StrEnum):
    COMPLETE_PR = "complete-pr"
    CHECKOUT_MERGE = "checkout-merge"
    EXACT = "exact"
    VALIDATED_TREE = "validated-tree"


class BaselineComparison(BaseModel):
    """A baseline travels with its head and additional changed-input evidence."""

    model_config = ConfigDict(frozen=True)
    base: str
    head: str
    kind: BaselineKind
    reason: str
    paths: tuple[str, ...] | None = None
    full: bool = False


class BaselinePlan(BaseModel):
    model_config = ConfigDict(frozen=True)
    primary: BaselineComparison
    alternate: BaselineComparison | None = None
    reused_failures: bool = False


class FailureEvidence(BaseModel):
    """Completion facts supplied by the exhaustive failure-evidence reader."""

    model_config = ConfigDict(frozen=True)
    sha: str = ""
    complete: bool = False
    truncated: bool = True
    stale: int = -1
    invalid: int = -1
    count: int = 0
    paths: tuple[str, ...] = ()

    def reusable(self) -> bool:
        return bool(
            self.sha
            and self.complete
            and not self.truncated
            and self.stale == 0
            and self.invalid == 0
            and self.count > 0
            and self.paths
        )


def comparison(repo: Path, base: str, head: str, kind: BaselineKind, *, pr_head: str = "") -> BaselineComparison:
    """Resolve only the identity named by the caller's explicit comparison contract."""
    if not base.strip("0"):
        return BaselineComparison(
            base=base, head=head, kind=kind, full=True, reason="no base commit to compare against"
        )
    if kind == BaselineKind.VALIDATED_TREE:
        raise ValueError("Validated trees require validated_comparison and its ancestry proof")
    try:
        git(repo, "cat-file", "-e", f"{base}^{{commit}}")
    except subprocess.CalledProcessError:
        return BaselineComparison(
            base=base, head=head, kind=kind, full=True, reason=f"base commit {base} is not in this checkout's history"
        )
    selected = base
    reason = "exact tree comparison"
    if kind == BaselineKind.COMPLETE_PR:
        try:
            ancestors = git(repo, "merge-base", "--all", base, head).splitlines()
        except subprocess.CalledProcessError:
            ancestors = []
        # INVARIANT: only a unique PR fork point can replace the event base.
        # Missing/ambiguous history must never manufacture a clean HEAD diff.
        if len(ancestors) == 1:
            selected, reason = ancestors[0], "complete PR diff from its unique fork point"
        else:
            reason = "unproven fork point; retain the conservative event base"
    elif kind == BaselineKind.CHECKOUT_MERGE:
        # Only the planner needs the selection extra. Bun and the collector can
        # import this policy from the base package without that optional dependency.
        from pytest_selective.git_operations import pull_request_merge_base

        # pytest-selective owns the current synthetic-merge parent proof.
        selected = pull_request_merge_base(repo, base, head, pr_head)
        reason = "proven checkout merge parent" if selected != base else "retain the event base"
    return BaselineComparison(base=selected, head=head, kind=kind, reason=reason)


def validated_comparison(repo: Path, base: str, head: str, *, validated_head: str = "") -> BaselineComparison:
    """Prove a historical tested tree without rewriting it to a merge base."""

    def sha(value: str) -> bool:
        return len(value) == 40 and all(char in "0123456789abcdef" for char in value)

    if not sha(base):
        raise ValueError("Missing committed selection base")
    resolved = git(repo, "rev-parse", "--verify", f"{base}^{{commit}}").strip()
    ancestor = resolved
    if validated_head:
        if not sha(validated_head):
            raise ValueError("Invalid validated PR head")
        parents = git(repo, "show", "-s", "--format=%P", resolved).strip().split()
        if len(parents) != 2 or parents[1] != validated_head:
            raise ValueError("Recorded merge does not have the validated PR head as its second parent")
        ancestor = validated_head
    git(repo, "merge-base", "--is-ancestor", ancestor, head)
    # INVARIANT: ancestry proves applicability; it does not replace the tested tree.
    return BaselineComparison(base=resolved, head=head, kind=BaselineKind.VALIDATED_TREE, reason="proven tested tree")


def fetched_delta(repo: Path, base: str, head: str) -> tuple[str, ...] | None:
    try:
        git(repo, "fetch", "--no-tags", "--depth=1", "origin", base)
        return tuple(git(repo, "diff", "--no-renames", "--name-only", base, head).splitlines())
    except subprocess.CalledProcessError:
        return None


def collect_plan(
    repo: Path,
    *,
    event: str,
    base: str,
    head: str,
    pr_base: str = "",
    before: str = "",
    validated: str = "",
    complete_paths: tuple[str, ...] | None = None,
    failures: FailureEvidence = FailureEvidence(),
) -> BaselinePlan:
    """Pair every candidate with complete inputs before admitting an alternate."""
    primary = comparison(
        repo, base, head, BaselineKind.COMPLETE_PR if event == "pull_request" and pr_base else BaselineKind.EXACT
    )
    if event == "pull_request":
        primary = primary.model_copy(update={"paths": complete_paths})
        use_failures = not validated and failures.reusable()
        candidate = validated or (failures.sha if use_failures else "")
        delta = fetched_delta(repo, candidate, head) if candidate else None
        if delta is not None:
            unresolved = failures.paths if use_failures else ()
            # INVARIANT: never intersect a tested-tree delta with PR-only paths.
            # Every unresolved failure follows BOTH independently complete plans.
            tested = BaselineComparison(
                base=candidate,
                head=head,
                kind=BaselineKind.VALIDATED_TREE,
                paths=tuple(sorted(set(delta + unresolved))),
                reason="admitted exact tested-tree delta",
            )
            alternate = None
            if pr_base and primary.base != candidate:
                alternate = primary.model_copy(
                    update={
                        "paths": None if complete_paths is None else tuple(sorted(set(complete_paths + unresolved)))
                    }
                )
            return BaselinePlan(primary=tested, alternate=alternate, reused_failures=use_failures)
    elif event == "push" and before and before.strip("0"):
        primary = primary.model_copy(update={"paths": fetched_delta(repo, before, head)})
    return BaselinePlan(primary=primary)
