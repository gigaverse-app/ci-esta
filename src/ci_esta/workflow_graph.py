"""GitHub Actions workflows as graph nodes, for every language CI-esta plans.

A workflow is not a global input. Each job is a node: it runs the lanes its conditions read
(`fromJSON(needs.PLANNER.outputs.lanes).LANE`), or every lane when it is the planner itself, and it
depends on the repository files it executes: paths named in `run`, `with` and local `uses` values,
followed into composite, JavaScript and Docker actions and reusable workflows. A changed job selects
its lanes; a changed file selects the lanes of the jobs that depend on it; a change outside `jobs:`
selects every lane the workflow runs. A file no job names, like a pull-request template, selects nothing.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

import yaml

from ci_esta.git import git

WORKFLOWS = ".github/workflows/"
#: A lane read from the planner's JSON output, by attribute or by index.
LANE_REFERENCE = re.compile(
    r"needs\.([A-Za-z_][A-Za-z0-9_-]*)\.outputs\.lanes\s*\)\s*"
    r"(?:\.\s*([A-Za-z_][A-Za-z0-9_]*)|\[\s*['\"]([A-Za-z_][A-Za-z0-9_]*)['\"]\s*\])"
)
#: Steps that decide which lanes run; their job's change can change every lane.
PLANNERS = re.compile(
    r"pytest-selective(?:/actions/(?:plan-lanes|test-impact))?@|pytest_selective\.ci\b"
    r"|ci-esta/actions/plan-work@|ci_esta\.testing\.work_plan\b"
)
#: A repository path inside a command line, an input or an action reference.
PATH_TOKEN = re.compile(r"[A-Za-z0-9_.@+\-]+(?:/[A-Za-z0-9_.@+\-]+)+|[A-Za-z0-9_\-]+\.[A-Za-z0-9]+")
#: Where an action refers to its own files.
ACTION_PATH = re.compile(r"(?:\$\{\{\s*github\.action_path\s*\}\}|\$\{?GITHUB_ACTION_PATH\}?)/([^\s'\"`;|&)]+)")
ALL = "*"
#: Commands that build, check, install or publish the repository's own package.
PACKAGE_COMMANDS = re.compile(
    r"\buv build\b|\bpython3? -m build\b|\bpip wheel\b|\b(?:hatch|poetry|pdm|flit) build\b"
    r"|\btwine (?:check|upload)\b|\bpip install (?:-e )?\.(?:\[|\s|$)|pypa/gh-action-pypi-publish"
    r"|\b(?:npm|pnpm|yarn) (?:pack|publish)\b|\bbun (?:pm pack|publish)\b"
)


def lane_references(text: str, planner: str | None = None) -> set[str]:
    """Lanes an expression reads from a planner's `lanes` output (any planner when None)."""
    return {match[1] or match[2] for match in LANE_REFERENCE.findall(text) if planner is None or match[0] == planner}


@dataclass
class Job:
    """One workflow job: the lanes it runs and the repository files it executes."""

    lanes: set[str] = field(default_factory=set)
    inputs: set[str] = field(default_factory=set)
    #: The job builds, checks, installs or publishes the package, so the package's inputs are its inputs too.
    packages: bool = False


def strings(value: Any) -> list[str]:
    """Every string inside a parsed YAML value, keys included."""
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [text for key, item in value.items() for text in (*strings(key), *strings(item))]
    if isinstance(value, list):
        return [text for item in value for text in strings(item)]
    return []


def is_workflow(path: str) -> bool:
    return path.startswith(WORKFLOWS) and PurePosixPath(path).suffix.lower() in {".yml", ".yaml"}


class WorkflowGraph:
    """The jobs of every workflow at one revision, with the files each executes."""

    def __init__(self, repo: Path, revision: str) -> None:
        self.repo = repo
        self.revision = revision
        listing = git(repo, "ls-tree", "-r", "-z", "--name-only", revision)
        self.files = {path for path in listing.split("\0") if path}
        self.directories = {str(parent) for path in self.files for parent in PurePosixPath(path).parents}
        self.documents: dict[str, dict[str, Any]] = {}
        self.jobs: dict[tuple[str, str], Job] = {}
        for path in sorted(self.files):
            if is_workflow(path):
                document = self.load(path)
                self.documents[path] = document
                for name, job in document["jobs"].items():
                    self.jobs[(path, str(name))] = self.describe(path, job)

    def load(self, path: str) -> dict[str, Any]:
        # Malformed YAML raises, so the planner falls back to every lane.
        document = yaml.safe_load(git(self.repo, "show", f"{self.revision}:{path}"))
        if not isinstance(document, dict) or not isinstance(document.get("jobs"), dict):
            raise ValueError(f"{path} at {self.revision} is not a workflow with a jobs mapping")
        return document

    def text(self, path: str) -> str | None:
        try:
            return git(self.repo, "show", f"{self.revision}:{path}")
        except subprocess.CalledProcessError:
            return None

    def describe(self, path: str, job: Any) -> Job:
        texts = strings(job)
        lanes = {lane for text in texts for lane in lane_references(text)}
        if any(PLANNERS.search(text) for text in texts):
            lanes = {ALL}
        packages = any(PACKAGE_COMMANDS.search(text) for text in texts)
        return Job(lanes=lanes, inputs=self.references(texts, set()), packages=packages)

    def references(self, texts: list[str], seen: set[str], action_dir: str | None = None) -> set[str]:
        """Repository files named in `texts`, followed through local actions and reusable workflows."""
        found: set[str] = set()
        candidates = [token.removeprefix("./") for text in texts for token in PATH_TOKEN.findall(text)]
        if action_dir is not None:
            candidates += [f"{action_dir}/{relative}" for text in texts for relative in ACTION_PATH.findall(text)]
        for candidate in candidates:
            candidate = candidate.rstrip(".,")
            if candidate in self.files:
                found.add(candidate)
                if is_workflow(candidate) and candidate not in seen:
                    seen.add(candidate)
                    found |= self.reusable(candidate, seen)
            elif candidate in self.directories and candidate not in seen:
                seen.add(candidate)
                found |= self.action(candidate, seen)
        return found

    def action(self, directory: str, seen: set[str]) -> set[str]:
        """A local action's metadata and the files its steps, entry points or image use."""
        for name in ("action.yml", "action.yaml"):
            metadata = f"{directory}/{name}"
            if metadata in self.files:
                document = yaml.safe_load(self.text(metadata) or "") or {}
                runs = document.get("runs", {}) if isinstance(document, dict) else {}
                texts = strings(runs)
                entry_points = [
                    f"{directory}/{runs[key]}"
                    for key in ("main", "pre", "post")
                    if isinstance(runs, dict) and isinstance(runs.get(key), str)
                ]
                image = runs.get("image") if isinstance(runs, dict) else None
                if isinstance(image, str) and not image.startswith("docker://"):
                    entry_points.append(f"{directory}/{image}")
                return {metadata, *(path for path in entry_points if path in self.files)} | self.references(
                    texts, seen, directory
                )
        return set()

    def reusable(self, path: str, seen: set[str]) -> set[str]:
        """A called workflow's own executed files; its jobs run inside the caller's job."""
        document = self.documents.get(path) or self.load(path)
        return self.references(strings(document.get("jobs", {})), seen)

    def package_lanes(self) -> set[str]:
        """Lanes gating a job that builds the package; a planner job is not one."""
        return {lane for job in self.jobs.values() if job.packages and ALL not in job.lanes for lane in job.lanes}

    def lanes_of_workflow(self, path: str) -> set[str]:
        return {lane for (workflow, _), job in self.jobs.items() if workflow == path for lane in job.lanes}


def changed_job_lanes(before: WorkflowGraph, after: WorkflowGraph, changed: set[str]) -> dict[str, set[str]]:
    """Map each reason to the lanes it selects (`*` meaning every lane)."""
    reasons: dict[str, set[str]] = {}
    for path in sorted(path for path in changed if is_workflow(path)):
        old, new = before.documents.get(path), after.documents.get(path)
        shared_old = {key: value for key, value in (old or {}).items() if key != "jobs"}
        shared_new = {key: value for key, value in (new or {}).items() if key != "jobs"}
        if old is None or new is None or shared_old != shared_new:
            # Triggers, env, defaults, permissions and concurrency reach every job, and an added or
            # deleted workflow adds or removes all of them.
            lanes = before.lanes_of_workflow(path) | after.lanes_of_workflow(path)
            if lanes:
                reasons[f"workflow changed: {path}"] = lanes
            continue
        for name in sorted(set(old["jobs"]) | set(new["jobs"])):
            if old["jobs"].get(name) != new["jobs"].get(name):
                key = (path, str(name))
                lanes = set()
                for graph in (before, after):
                    if key in graph.jobs:
                        lanes |= graph.jobs[key].lanes
                if lanes:
                    reasons[f"workflow job changed: {path}#{name}"] = lanes
    for graph in (before, after):
        for (path, name), job in graph.jobs.items():
            for file in sorted(job.inputs & changed):
                if job.lanes:
                    reasons.setdefault(f"workflow input: {file} (run by {path}#{name})", set()).update(job.lanes)
    return reasons
