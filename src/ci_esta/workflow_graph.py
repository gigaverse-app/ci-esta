"""GitHub Actions workflows as graph nodes, for every language CI-esta plans.

A workflow is not a global input. Each job is a node: it runs the lanes its conditions read
(`fromJSON(needs.PLANNER.outputs.lanes).LANE`), or every lane when it is the planner itself, and it
depends on the repository files it executes: paths named in `run`, `with` and local `uses` values,
followed into composite, JavaScript and Docker actions and reusable workflows, plus the files an
executed file declares it reads (`# gv:test-dependency: PATH`, pytest-selective's syntax, in a `#` or
`//` comment), since no command line names what a script opens by path. A changed job selects
its lanes; a changed file selects the lanes of the jobs that depend on it; a change outside `jobs:`
selects every lane the workflow runs. A file no job names, like a pull-request template, selects nothing.
"""

from __future__ import annotations

import posixpath
import re
import subprocess
import tomllib
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
#: A job other jobs read lanes from: the planner. Its change can change every lane.
PLANNER_REFERENCE = re.compile(r"needs\.([A-Za-z_][A-Za-z0-9_-]*)\.outputs\.lanes\b")
#: A repository path inside a command line, an input or an action reference.
PATH_TOKEN = re.compile(r"[A-Za-z0-9_.@+\-]+(?:/[A-Za-z0-9_.@+\-]+)+|[A-Za-z0-9_\-]+\.[A-Za-z0-9]+")
#: A line whose comment declares a file the script reads: pytest-selective's declaration syntax.
DECLARATION_LINE = re.compile(r"^\s*(?:#|//)(.*gv:test-dependency.*)$")
#: Where an action refers to its own files.
ACTION_PATH = re.compile(r"(?:\$\{\{\s*github\.action_path\s*\}\}|\$\{?GITHUB_ACTION_PATH\}?)/([^\s'\"`;|&)]+)")
ALL = "*"
#: `python -m MODULE` or `"$INTERPRETER" -m MODULE`: the job runs that module and everything it imports.
#: Only a module that resolves to a repository file counts, so `git commit -m` and the like match nothing.
PYTHON_MODULE = re.compile(r"(?:python\w*|\$\{?[A-Za-z_]\w*\}?)\b[^\n;&|]*?\s-m\s+([A-Za-z_][\w.]*)", re.IGNORECASE)
#: A dotted module name passed to a wrapper (`bash run.sh pkg.tool`); kept only if it is a repository module.
DOTTED_NAME = re.compile(r"(?<![\w.$/{-])([A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)+)(?![\w./}-])")
#: A shell variable reference: `$NAME` or `${NAME}`.
VARIABLE = re.compile(r"\$\{?([A-Za-z_][A-Za-z0-9_]*)\}?")
#: An action input inside a composite action's step.
INPUT_EXPRESSION = re.compile(r"\$\{\{\s*inputs\.([A-Za-z0-9_-]+)\s*\}\}")
#: Inputs of another repository's action that hold a command (`pytest-command`, `run`, `script`).
COMMAND_INPUT = re.compile(r"(?:^|-)(?:command|run|script)s?$")
#: Actions that run the repository's Bun tests from an inventory they discover.
BUN_TEST_ACTIONS = re.compile(r"/actions/run-bun-tests@")
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
    #: The lanes the job-level condition reads; a step's own condition gates only that step.
    job_lanes: set[str] = field(default_factory=set)
    #: Python modules the job runs (`python -m X`, a console script), directly or through its local actions.
    modules: set[str] = field(default_factory=set)


def strings(value: Any) -> list[str]:
    """Every string inside a parsed YAML value, keys included."""
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [text for key, item in value.items() for text in (*strings(key), *strings(item))]
    if isinstance(value, list):
        return [text for item in value for text in strings(item)]
    return []


def job_needs(job: Any) -> list[str]:
    """A job's `needs`, which YAML allows as one string or a list."""
    needs = job.get("needs", []) if isinstance(job, dict) else []
    return [needs] if isinstance(needs, str) else [str(need) for need in needs] if isinstance(needs, list) else []


def prerequisites(needs: dict[str, list[str]], roots: list[str]) -> set[str]:
    """The roots and every job they wait for, transitively: the jobs whose failure can reach a gate."""
    reached: set[str] = set()
    pending = list(roots)
    while pending:
        name = pending.pop()
        if name not in reached and name in needs:
            reached.add(name)
            pending.extend(needs[name])
    return reached


def working_directory(document: dict[str, Any], job: Any, step: Any) -> str | None:
    """The repository directory a step's `run` executes in: the step's, the job's or the workflow's default."""
    for owner in (step, job, document):
        if not isinstance(owner, dict):
            continue
        value = owner.get("working-directory") if owner is step else None
        if value is None:
            defaults = owner.get("defaults")
            run = defaults.get("run") if isinstance(defaults, dict) else None
            value = run.get("working-directory") if isinstance(run, dict) else None
        if isinstance(value, str):
            # An expression names a directory only at run time.
            return None if "${{" in value else posixpath.normpath(value.strip().removeprefix("./"))
    return None


def run_steps(document: dict[str, Any], job: Any) -> list[tuple[str, str | None]]:
    """Each `run` command of a job, with the repository directory it executes in (None for the root)."""
    steps = job.get("steps") if isinstance(job, dict) else None
    found = []
    for step in steps if isinstance(steps, list) else []:
        if isinstance(step, dict) and isinstance(step.get("run"), str):
            directory = working_directory(document, job, step)
            found.append((step["run"], None if directory in {None, "."} else directory))
    return found


def directory_of(value: object) -> str | None:
    """A repository directory from a `working-directory` value; None for the root or a run-time expression."""
    if not isinstance(value, str) or "${{" in value:
        return None
    directory = posixpath.normpath(value.strip().removeprefix("./"))
    return None if directory == "." else directory


def foreign_checkouts(job: Any) -> list[str]:
    """Directories where a job checks out another repository; commands there run its files, not ours."""
    steps = job.get("steps") if isinstance(job, dict) else None
    found = []
    for step in steps if isinstance(steps, list) else []:
        if not isinstance(step, dict) or not str(step.get("uses", "")).startswith("actions/checkout@"):
            continue
        options = step.get("with") if isinstance(step.get("with"), dict) else {}
        if options.get("repository") and (directory := directory_of(options.get("path"))):
            found.append(directory)
    return found


def local_actions(job: Any) -> list[str]:
    """Directories of the local actions a job's steps use, the repository root included (`uses: ./`)."""
    steps = job.get("steps") if isinstance(job, dict) else None
    return [
        posixpath.normpath(step["uses"].removeprefix("./") or ".")
        for step in (steps if isinstance(steps, list) else [])
        if isinstance(step, dict) and isinstance(step.get("uses"), str) and step["uses"].startswith("./")
    ]


def expanded_runs(runs: Any) -> list[str]:
    """A composite action's `run` commands with their step's `env` values substituted.

    Actions alias their own directory (`SHARED_ACTION_PATH: ${{ github.action_path }}`) or a script in it
    (`HELPER: ${{ github.action_path }}/../../scripts/helper.py`); substituted, those paths resolve.
    """
    steps = runs.get("steps") if isinstance(runs, dict) else None
    found = []
    for step in steps if isinstance(steps, list) else []:
        if not isinstance(step, dict) or not isinstance(step.get("run"), str):
            continue
        env = (
            {str(key): str(value) for key, value in (step.get("env") or {}).items()}
            if isinstance(step.get("env"), dict)
            else {}
        )
        if env:
            found.append(VARIABLE.sub(lambda match: env.get(match[1], match[0]), step["run"]))
    return found


def is_workflow(path: str) -> bool:
    return path.startswith(WORKFLOWS) and PurePosixPath(path).suffix.lower() in {".yml", ".yaml"}


def inside(directory: str, relative: str) -> str:
    """A path relative to a repository directory, as a repository path."""
    return posixpath.normpath(f"{directory}/{relative.removeprefix('./')}")


class WorkflowGraph:
    """The jobs of every workflow at one revision, with the files each executes."""

    def __init__(self, repo: Path, revision: str) -> None:
        self.repo = repo
        self.revision = revision
        listing = git(repo, "ls-tree", "-r", "-z", "--name-only", revision)
        self.files = {path for path in listing.split("\0") if path}
        self.directories = {str(parent) for path in self.files for parent in PurePosixPath(path).parents}
        self.documents: dict[str, dict[str, Any]] = {}
        self.declarations: dict[str, set[str]] = {}
        #: Each local action's metadata and the commands its `runs` holds.
        self.action_texts: dict[str, list[str]] = {}
        #: The repository's console scripts (`[project.scripts]`), name to module.
        self.scripts = self.console_scripts()
        self.jobs: dict[tuple[str, str], Job] = {}
        for path in sorted(self.files):
            if is_workflow(path):
                document = self.load(path)
                self.documents[path] = document
                for name, job in document["jobs"].items():
                    self.jobs[(path, str(name))] = self.describe(document, job)
                # The planner is the job whose `lanes` output other jobs read, or that declares one; using a
                # planning action to test it (a smoke job) does not make a job the planner.
                read = {match for text in strings(document["jobs"]) for match in PLANNER_REFERENCE.findall(text)}
                for name, job in document["jobs"].items():
                    outputs = job.get("outputs") if isinstance(job, dict) else None
                    if str(name) in read or (isinstance(outputs, dict) and "lanes" in outputs):
                        self.jobs[(path, str(name))].lanes = {ALL}
                        self.jobs[(path, str(name))].job_lanes = {ALL}

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

    def describe(self, document: dict[str, Any], job: Any) -> Job:
        texts = strings(job)
        lanes = {lane for text in texts for lane in lane_references(text)}
        packages = any(PACKAGE_COMMANDS.search(text) for text in texts)
        # A command in a working directory names its files relative to that directory.
        relative = [
            posixpath.normpath(f"{directory}/{token.removeprefix('./')}")
            for command, directory in run_steps(document, job)
            if directory is not None
            for token in PATH_TOKEN.findall(command)
        ]
        seen: set[str] = set()
        inputs = self.references([*texts, *relative], seen)
        for directory in local_actions(job):
            if directory == "." and directory not in seen:
                # `uses: ./` is the repository's own action, which no path token names.
                seen.add(directory)
                inputs |= self.action(directory, seen)
        condition = job.get("if") if isinstance(job, dict) else None
        job_lanes = lane_references(str(condition)) if condition is not None else set()
        commands = [*texts, *(text for path in sorted(inputs) for text in self.action_texts.get(path, []))]
        return Job(
            lanes=lanes,
            inputs=inputs,
            packages=packages,
            job_lanes=job_lanes & lanes or lanes,
            modules=self.modules(commands),
        )

    def console_scripts(self) -> dict[str, str]:
        """Every tracked project's `[project.scripts]`, as name to module."""
        found: dict[str, str] = {}
        for path in sorted(path for path in self.files if PurePosixPath(path).name == "pyproject.toml"):
            try:
                project = tomllib.loads(self.text(path) or "").get("project", {})
            except tomllib.TOMLDecodeError:
                continue
            scripts = project.get("scripts") if isinstance(project, dict) else None
            for name, target in (scripts if isinstance(scripts, dict) else {}).items():
                found[str(name)] = str(target).split(":", 1)[0].strip()
        return found

    def modules(self, commands: list[str]) -> set[str]:
        """Python modules `commands` run: `python -m X`, or a console script of this repository."""
        found = {match for text in commands for match in (*PYTHON_MODULE.findall(text), *DOTTED_NAME.findall(text))}
        for name, module in self.scripts.items():
            script = re.compile(rf"(?:^|[\s;&|(`'\"]){re.escape(name)}(?=[\s;&|)`'\"]|$)", re.MULTILINE)
            if any(script.search(text) for text in commands):
                found.add(module)
        return found

    def references(self, texts: list[str], seen: set[str], action_dir: str | None = None) -> set[str]:
        """Repository files named in `texts`, followed through local actions and reusable workflows."""
        found: set[str] = set()
        candidates = [token.removeprefix("./") for text in texts for token in PATH_TOKEN.findall(text)]
        if action_dir is not None:
            candidates += [inside(action_dir, relative) for text in texts for relative in ACTION_PATH.findall(text)]
        for candidate in candidates:
            candidate = candidate.rstrip(".,")
            if candidate in self.files:
                found.add(candidate)
                if is_workflow(candidate) and candidate not in seen:
                    seen.add(candidate)
                    found |= self.reusable(candidate, seen)
                elif candidate not in seen:
                    seen.add(candidate)
                    found |= self.declared(candidate)
            elif candidate in self.directories and candidate not in seen:
                seen.add(candidate)
                found |= self.action(candidate, seen)
        return found

    def commands(self, workflow: str, name: str) -> list[tuple[str, str | None]]:
        """Each command a job runs, with the repository directory it runs in (None for the root).

        Its own `run` steps; the `run` steps of local composite actions it uses, with their inputs
        filled in; command-valued inputs of other actions (`pytest-command`); and `bun test` for an
        action that runs the repository's Bun tests. Commands inside another repository's checkout
        are left out.
        """
        document = self.documents[workflow]
        job = document["jobs"][name]
        found = run_steps(document, job)
        steps = job.get("steps") if isinstance(job, dict) else None
        for step in steps if isinstance(steps, list) else []:
            if not isinstance(step, dict) or not isinstance(step.get("uses"), str):
                continue
            uses = step["uses"]
            options = step.get("with") if isinstance(step.get("with"), dict) else {}
            directory = directory_of(options.get("working-directory"))
            if BUN_TEST_ACTIONS.search(uses):
                found.append(("bun test", directory))
            elif uses.startswith("./"):
                found.extend(self.composite_commands(posixpath.normpath(uses.removeprefix("./") or "."), options))
            else:
                found.extend(
                    (value, directory)
                    for key, value in options.items()
                    if isinstance(value, str) and COMMAND_INPUT.search(str(key))
                )
        from pytest_selective.impact_graph import within

        foreign = foreign_checkouts(job)
        return [
            (command, directory)
            for command, directory in found
            if directory is None or not any(within(directory, path) for path in foreign)
        ]

    def composite_commands(self, directory: str, options: dict[str, Any]) -> list[tuple[str, str | None]]:
        """The `run` steps of a local composite action, with the caller's inputs or their defaults filled in."""
        metadata = next(
            (
                inside(directory, name)
                for name in ("action.yml", "action.yaml")
                if inside(directory, name) in self.files
            ),
            None,
        )
        if metadata is None:
            return []
        document = yaml.safe_load(self.text(metadata) or "") or {}
        if not isinstance(document, dict):
            return []
        declared = document.get("inputs") if isinstance(document.get("inputs"), dict) else {}
        values = {
            str(key): str(options.get(key, spec.get("default", "") if isinstance(spec, dict) else ""))
            for key, spec in declared.items()
        }

        def filled(text: object) -> object:
            if not isinstance(text, str):
                return text
            return INPUT_EXPRESSION.sub(lambda match: values.get(match[1], match[0]), text)

        runs = document.get("runs") if isinstance(document.get("runs"), dict) else {}
        steps = runs.get("steps") if isinstance(runs.get("steps"), list) else []
        return [
            (str(filled(step["run"])), directory_of(filled(step.get("working-directory"))))
            for step in steps
            if isinstance(step, dict) and isinstance(step.get("run"), str)
        ]

    def declared(self, path: str) -> set[str]:
        """Files `path` declares it reads, and theirs in turn, in pytest-selective's syntax; an invalid one raises."""
        from pytest_selective.impact_graph import declared_inputs, dependency_comment

        if path not in self.declarations:
            self.declarations[path] = set()
            text = self.text(path) or ""
            files = dict.fromkeys(self.files, "") if "gv:test-dependency" in text else {}
            found: set[str] = set()
            for number, line in enumerate(text.splitlines() if files else [], 1):
                if (match := DECLARATION_LINE.match(line)) and (comment := dependency_comment(match[1], number)):
                    found |= declared_inputs(comment, files, path)
            for target in sorted(found):
                found |= self.declared(target)
            self.declarations[path] = found
        return self.declarations[path]

    def action(self, directory: str, seen: set[str]) -> set[str]:
        """A local action's metadata and the files its steps, entry points or image use."""
        for name in ("action.yml", "action.yaml"):
            metadata = inside(directory, name)
            if metadata in self.files:
                document = yaml.safe_load(self.text(metadata) or "") or {}
                runs = document.get("runs", {}) if isinstance(document, dict) else {}
                texts = [*strings(runs), *expanded_runs(runs)]
                entry_points = [
                    inside(directory, runs[key])
                    for key in ("main", "pre", "post")
                    if isinstance(runs, dict) and isinstance(runs.get(key), str)
                ]
                self.action_texts[metadata] = texts
                image = runs.get("image") if isinstance(runs, dict) else None
                if isinstance(image, str) and not image.startswith("docker://"):
                    entry_points.append(inside(directory, image))
                return {metadata, *(path for path in entry_points if path in self.files)} | self.references(
                    texts, seen, directory
                )
        return set()

    def reusable(self, path: str, seen: set[str]) -> set[str]:
        """A called workflow's own executed files; its jobs run inside the caller's job."""
        document = self.documents.get(path) or self.load(path)
        return self.references(strings(document.get("jobs", {})), seen)

    def package_lanes(self) -> set[str]:
        """Lanes gating a job that builds the package, by its job-level condition; a planner job is not one."""
        return {lane for job in self.jobs.values() if job.packages and ALL not in job.lanes for lane in job.job_lanes}

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
