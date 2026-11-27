"""Admit Bun's native selection only when Git and repository declarations prove its scope."""

import json
import subprocess
from fnmatch import fnmatchcase
from pathlib import Path

from selective_deps import DependencyDeclarationError

from ci_esta.git import git, tracked_files
from ci_esta.testing.baseline_policy import validated_comparison
from ci_esta.testing.bun.discovery import test_files
from ci_esta.testing.bun.graph import test_inputs, test_preloads, unmodeled_inputs
from ci_esta.testing.bun.models import (
    BUN_ENVIRONMENT_NAMES,
    TEST_FILE,
    BunPolicy,
    Inventory,
    SelectionPlan,
    SelectionRequest,
)
from ci_esta.testing.bun.readers import names_untracked_inputs
from ci_esta.testing.dependencies import declared_edges
from ci_esta.workflow_graph import is_workflow, load_workflow, observes_completion


def safe_path(value: str) -> bool:
    return (bool(value) and not value.startswith("/")
            and not any(char in value for char in "\\\n\r\0:")
            and not any(part in {".", ".."} for part in value.split("/")))


def read_inventory(path: Path, cwd: Path) -> Inventory:
    inventory = Inventory.model_validate_json(path.read_text(encoding="utf-8"))
    if len(set(inventory.files)) != len(inventory.files) or len(set(inventory.always_run_files)) != len(inventory.always_run_files):
        raise ValueError("Duplicate inventory entries")
    for file in inventory.files:
        target = cwd / file
        if (not safe_path(file) or not TEST_FILE.search(file)
                or target.is_symlink() or not target.is_file()):
            raise ValueError(f"Invalid test file: {file}")
    if not set(inventory.always_run_files).issubset(inventory.files):
        raise ValueError("Always-run tests must belong to the inventory")
    return inventory.model_copy(update={"files": sorted(inventory.files)})


def _policy(request: SelectionRequest) -> BunPolicy:
    policy = BunPolicy.model_validate_json((request.cwd / request.policy_file).read_text())
    paths = [*policy.scoped_roots, *policy.unaffected_paths, *policy.unaffected_roots,
             *policy.source_extensions, *policy.runtime_roots,
             *(path for reader in policy.reviewed_readers.values() for path in reader.inputs)]
    if not all(safe_path(path) for path in paths):
        raise ValueError("Invalid selection policy paths")
    if not all(root.endswith("/") for root in [*policy.scoped_roots, *policy.runtime_roots, *policy.unaffected_roots]):
        raise ValueError("Policy roots must end with /")
    return policy


def _declared_plan(request: SelectionRequest, plan: SelectionPlan, changes: list[tuple[str, str]]) -> SelectionPlan:
    """Bun imports plus the shared portable declarations, without a hash registry."""
    files = set(tracked_files(request.cwd))
    declared_edges(request.cwd, files)  # Invalid declarations must not become a successful full fallback.
    for status, path in changes:
        environment = any(fnmatchcase(Path(path).name, pattern) for pattern in BUN_ENVIRONMENT_NAMES)
        if status not in {'A', 'M'} or environment:
            plan.reason = f"Full suite for environment or removed input: {path}"
            return plan
    tests = request.test_files if request.test_files is not None else test_files(files)
    preloads = sorted(set(test_preloads(request.cwd, files)) | set(request.preloads))
    if not set(tests + preloads).issubset(files):
        raise ValueError('Test inventory or preloads are outside the tracked inputs')
    graph = test_inputs(request.cwd, sorted(set(tests + preloads)), request.bun, files)
    changed = set(plan.changed_files)
    if any(graph[preload] & changed for preload in preloads):
        plan.reason = 'Full suite for a changed preload dependency'
        return plan
    for path in unmodeled_inputs(changed, graph):
        # Only otherwise-unexplained inputs need their triggers checked. Direct test
        # and preload reads still see the complete change set.
        if is_workflow(path) and all(
            observes_completion(load_workflow(request.cwd, revision, path))
            for revision in (plan.base, plan.tested_sha)
        ):
            continue
        plan.reason = f"Full suite for an undeclared non-import input: {path}"
        return plan
    affected = {test for test in tests if graph[test] & changed} - set(request.always_run_files)
    plan.selected_files = sorted(affected | set(request.always_run_files))
    plan.mode = 'scoped' if affected else 'none'
    plan.reason = (f"Bun import graph and shared dependency declarations against {plan.base}; {len(affected)} affected files"
                   if affected else "No test reaches a changed file; always-run tests still execute")
    return plan


def plan_affected_tests(request: SelectionRequest) -> SelectionPlan:
    plan = SelectionPlan(reason=request.checkpoint_reason or "Full checkpoint requested",
                         fallback="fallback" in (request.checkpoint_reason or ""),
                         validated_head=request.validated_head or None)
    try:
        plan.tested_sha = git(request.cwd, "rev-parse", "HEAD").strip()
        if request.full:
            return plan
        plan.base = validated_comparison(
            request.cwd, request.base, plan.tested_sha, validated_head=request.validated_head
        ).base
        if git(request.cwd, "status", "--porcelain", "--untracked-files=no").strip():
            raise ValueError("Tracked worktree differs from the planned commit")
        if git(request.cwd, "ls-files", "--others", "--exclude-standard").strip():
            raise ValueError("Untracked inputs are outside the committed selection contract")
        entries = git(request.cwd, "diff", "--name-status", "--no-renames", "-z", plan.base, plan.tested_sha, "--").split("\0")
        changes = list(zip(entries[0:-1:2], entries[1:-1:2], strict=True))
        plan.changed_files = [path for _, path in changes]
        if not request.policy_file:
            return _declared_plan(request, plan, changes)
        policy = _policy(request)

        def source(path: str) -> bool:
            return path.startswith(tuple(policy.scoped_roots)) and Path(path).suffix in policy.source_extensions

        def unaffected(path: str) -> bool:
            return path in policy.unaffected_paths or (path.startswith(tuple(policy.unaffected_roots)) and path.endswith(".md"))

        reader_inputs = [path for reader in policy.reviewed_readers.values() for path in reader.inputs]
        for status, path in changes:
            if (status not in {"A", "M"} or (not source(path) and not unaffected(path))
                    or any(path.startswith(item) if item.endswith("/") else path == item for item in reader_inputs)):
                plan.reason = f"Full suite for shared, non-import, deleted or unknown input: {path}"
                return plan
        for entry in git(request.cwd, "ls-files", "--stage", "-z").split("\0"):
            if not entry:
                continue
            metadata, path = entry.split("\t", 1)
            if path in request.always_run_files or not path.startswith(tuple(policy.runtime_roots)):
                continue
            mode, blob, _ = metadata.split()
            if mode not in {"100644", "100755"}:
                raise ValueError(f"Non-regular source input: {path}")
            if Path(path).suffix not in policy.source_extensions:
                continue
            if names_untracked_inputs((request.cwd / path).read_text()):
                reader = policy.reviewed_readers.get(path)
                if reader is not None and reader.blob == blob:
                    continue
                plan.fallback = True
                plan.reason = f"Import analysis cannot prove file-based or computed dependencies in {path}"
                return plan
        count = sum(source(path) for _, path in changes)
        plan.mode = "scoped" if count else "none"
        plan.reason = (f"Bun import analysis against {plan.base}; {count} source/test files changed" if count
                       else "Only declared unaffected inputs changed; always-run tests still execute")
    except DependencyDeclarationError:
        raise
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        plan.fallback = True
        plan.reason = f"Selection unavailable; run the full suite: {str(error).splitlines()[0]}"
    return plan


def read_test_selection(path: Path, request: SelectionRequest) -> SelectionPlan:
    try:
        saved = SelectionPlan.model_validate_json(path.read_text(encoding="utf-8"))
        actual = plan_affected_tests(request.model_copy(update={
            "base": saved.base, "validated_head": saved.validated_head or "", "full": request.full or saved.mode == "full",
        }))
        if actual.tested_sha != saved.tested_sha or actual.mode != saved.mode:
            raise ValueError("Plan does not match the checked-out revision and current policy")
        return actual
    except (OSError, ValueError, json.JSONDecodeError) as error:
        return plan_affected_tests(request.model_copy(update={"full": True})).model_copy(update={
            "fallback": True,
            "reason": f"Missing or invalid execution plan; run the full suite: {str(error).splitlines()[0]}",
        })
