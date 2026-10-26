"""Admit Bun's native selection only when Git and repository declarations prove its scope."""

import json
import re
import subprocess
from pathlib import Path

from ci_esta.testing.bun.models import BunPolicy, Inventory, SelectionPlan, SelectionRequest

OPAQUE_DEPENDENCY = re.compile(
    r"\b(?:Bun\s*\.\s*file|readFile(?:Sync)?|import\s*\.\s*meta\s*\.\s*glob)\b"
    r"|[\"'](?:node:)?fs(?:/promises)?[\"']|\b(?:import|require)\s*\(\s*(?!\s*[\"'])[^\s]"
)
SHA = re.compile(r"[0-9a-f]{40}\Z")


def safe_path(value: str) -> bool:
    return (bool(value) and not value.startswith("/")
            and not any(char in value for char in "\\\n\r\0:")
            and not any(part in {".", ".."} for part in value.split("/")))


def git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout


def read_inventory(path: Path, cwd: Path) -> Inventory:
    inventory = Inventory.model_validate_json(path.read_text())
    if len(set(inventory.files)) != len(inventory.files) or len(set(inventory.always_run_files)) != len(inventory.always_run_files):
        raise ValueError("Duplicate inventory entries")
    for file in inventory.files:
        target = cwd / file
        if (not safe_path(file) or not re.search(r"[._](?:test|spec)\.[cm]?[jt]sx?$", file)
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


def _comparison_base(request: SelectionRequest, tested_sha: str) -> str:
    if not SHA.fullmatch(request.base):
        raise ValueError("Missing committed selection base")
    base = git(request.cwd, "rev-parse", "--verify", f"{request.base}^{{commit}}").strip()
    ancestor = base
    if request.validated_head:
        if not SHA.fullmatch(request.validated_head):
            raise ValueError("Invalid validated PR head")
        parents = git(request.cwd, "show", "-s", "--format=%P", base).strip().split()
        if len(parents) != 2 or parents[1] != request.validated_head:
            raise ValueError("Recorded merge does not have the validated PR head as its second parent")
        ancestor = request.validated_head
    git(request.cwd, "merge-base", "--is-ancestor", ancestor, tested_sha)
    return base


def plan_affected_tests(request: SelectionRequest) -> SelectionPlan:
    plan = SelectionPlan(reason=request.checkpoint_reason or "Full checkpoint requested",
                         fallback="fallback" in (request.checkpoint_reason or ""),
                         validated_head=request.validated_head or None)
    try:
        plan.tested_sha = git(request.cwd, "rev-parse", "HEAD").strip()
        if request.full:
            return plan
        plan.base = _comparison_base(request, plan.tested_sha)
        if git(request.cwd, "status", "--porcelain", "--untracked-files=no").strip():
            raise ValueError("Tracked worktree differs from the planned commit")
        policy = _policy(request)
        if git(request.cwd, "ls-files", "--others", "--exclude-standard").strip():
            raise ValueError("Untracked inputs are outside the committed selection contract")
        entries = git(request.cwd, "diff", "--name-status", "--no-renames", "-z", plan.base, plan.tested_sha, "--").split("\0")
        changes = list(zip(entries[0:-1:2], entries[1:-1:2], strict=True))
        plan.changed_files = [path for _, path in changes]

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
            if OPAQUE_DEPENDENCY.search((request.cwd / path).read_text()):
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
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        plan.fallback = True
        plan.reason = f"Selection unavailable; run the full suite: {str(error).splitlines()[0]}"
    return plan


def read_test_selection(path: Path, request: SelectionRequest) -> SelectionPlan:
    try:
        saved = SelectionPlan.model_validate_json(path.read_text())
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
