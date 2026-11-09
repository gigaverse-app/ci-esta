"""Lanes inferred from the workflow, so a repository needs no lane file.

The lanes are the names the workflow's job conditions read from the planner's output. A lane's test
roots are the paths its jobs pass to a test command (`pytest X`, `python -m pytest X`, `bun test X`,
`node --test X`, `vitest X`, `jest X`, `unittest discover -s X`), relative to the step's working
directory. A pytest command with no path takes pytest's `testpaths`, or the whole repository; a
JavaScript runner with no path (`node --test`, `npm test`) takes its working directory. A lane whose jobs run no test command (a build, a smoke check) is selected through the
jobs it gates. A test no lane claims still runs every lane, so a guess that misses errs toward work.

The reviewed pytest policy is taken from the base commit: a pull request that changes how pytest
collects runs every lane, as a reviewed lane file would until its fingerprints were refreshed.
"""

from __future__ import annotations

import json
import posixpath
import re
import shlex
import tomllib
from pathlib import Path, PurePosixPath

from pydantic import BaseModel, Field
from pytest_selective.ci import Lane, LaneConfig
from pytest_selective.impact_graph import policy_fingerprints
from pytest_selective.impact_models import GitTree, ImpactConfig
from pytest_selective.input_policy import DEFAULT_GLOBAL_INPUTS

from ci_esta.git import git
from ci_esta.testing.lane_rules import Rule, effective
from ci_esta.workflow_graph import ALL, WorkflowGraph, inside

#: The words that start a test command, and the arguments after them that are paths.
TEST_COMMAND = re.compile(
    r"(?:^|[\s;&|(])(?:uv run (?:--[\w-]+(?:[ =]\S+)? )*)?(pytest-selective execute-plan|pytest-selective run|pytest|python3? -m pytest)(?![\w-])(.*)"
)
#: JavaScript test runners: with no path they collect the tests under their working directory.
JS_TEST_COMMAND = re.compile(
    r"(?:^|[\s;&|(])(?:npx |bunx |pnpm exec |yarn )?(bun test|node --test|vitest(?: run)?|jest"
    r"|(?:npm|pnpm|yarn|bun run) test|npm run test|npm t)(?![\w:-])(.*)"
)
UNITTEST = re.compile(r"python3? -m unittest discover\b.*?(?:-s|--start-directory)[ =](\S+)")
#: A repository script that runs the tests (`python scripts/run_ci_tests.py`): it collects pytest's defaults.
TEST_WRAPPER = re.compile(r"\bpython3? (?:-\S+ )*(\S*run\w*tests?\w*\.py)\b")
#: A shell script a command runs; its own test commands give the roots.
SHELL_SCRIPT = re.compile(r"(?:^|[\s;&|(])(?:bash |sh |exec )?((?:\.{0,2}/)?[\w.@+-]+(?:/[\w.@+-]+)*\.sh)\b")
#: `cd DIR && ...` or `cd DIR; ...` before a command.
CHANGE_DIRECTORY = re.compile(r"^\s*cd\s+(['\"]?)([^'\"\s;&|]+)\1\s*(?:&&|;)\s*(.*)$")
#: `uv run --directory DIR`, which runs the command inside DIR.
UV_DIRECTORY = re.compile(r"\buv (?:run )?(?:--[\w-]+(?:[ =]\S+)? )*?--directory[ =](['\"]?)([^'\"\s]+)\1")
#: Options whose next word is a value, not a test path.
VALUED_OPTIONS = {
    "-c",
    "--config",
    "-k",
    "-m",
    "-p",
    "-n",
    "-o",
    "--rootdir",
    "--confcutdir",
    "--junitxml",
    "--basetemp",
    "--cov",
    "--cov-report",
    "--timeout",
    "--durations",
    "--maxfail",
    "--preload",
    "--bail",
}


def paths_after(
    arguments: str, files: set[str], directories: set[str], directory: str | None = None
) -> list[str] | None:
    """Repository paths among a test command's arguments, read from `directory`; None when it names none."""
    try:
        words = shlex.split(arguments.split("&&")[0].split(";")[0].split("|")[0])
    except ValueError:
        return None
    found, skip = [], False
    for word in words:
        if skip:
            skip = False
            continue
        if word in VALUED_OPTIONS:
            skip = True
            continue
        if word.startswith("-"):
            continue
        path = word.split("::")[0].removeprefix("./").rstrip("/")
        if directory is not None:
            path = posixpath.normpath(f"{directory}/{path}")
        if path in files or path in directories:
            found.append(path)
    return found or None


def joined(directory: str | None, path: str) -> str | None:
    """`path` read from `directory`, as a repository path; None for the root."""
    if path.startswith(("$", "~", "/")):
        return directory
    value = inside(directory or ".", path)
    return None if value == "." else value


def line_roots(line: str, directory: str | None, graph: WorkflowGraph, repo: Path, nested: bool = False) -> list[str]:
    """The test roots one command line runs, read from `directory`; a shell script is read once, not recursively."""
    while match := CHANGE_DIRECTORY.match(line):
        directory, line = joined(directory, match[2]), match[3]
    if match := UV_DIRECTORY.search(line):
        directory = joined(directory, match[2])
    files, directories = graph.files, graph.directories
    if match := UNITTEST.search(line):
        return [joined(directory, match.group(1)) or "."]
    if match := TEST_COMMAND.search(line):
        return paths_after(match.group(2), files, directories, directory) or (
            [directory] if directory is not None else default_roots(repo)
        )
    if match := JS_TEST_COMMAND.search(line):
        return paths_after(match.group(2), files, directories, directory) or [directory or "."]
    if (match := TEST_WRAPPER.search(line)) and match.group(1).removeprefix("./") in files:
        return default_roots(repo)
    if not nested and (match := SHELL_SCRIPT.search(line)):
        script = next(
            (path for path in (joined(directory, match[1]), joined(None, match[1])) if path in files),
            None,
        )
        if script is not None:
            here = posixpath.dirname(script) or None
            for inner in (graph.text(script) or "").splitlines():
                if not inner.lstrip().startswith("#") and (found := line_roots(inner, directory, graph, repo, True)):
                    # A runner with no path in a script collects the script's own directory.
                    defaults = [directory] if directory is not None else default_roots(repo)
                    return [here or "."] if found == defaults and here is not None else found
    return []


def module_roots(graph: WorkflowGraph) -> list[str]:
    """Where imports resolve: each project's source layout, pytest's `pythonpath` and Ruff's `src`, then `src` and `.`."""
    found: list[str] = []
    for pyproject in sorted(path for path in graph.files if PurePosixPath(path).name == "pyproject.toml"):
        project = posixpath.dirname(pyproject)
        try:
            document = tomllib.loads(graph.text(pyproject) or "")
        except tomllib.TOMLDecodeError:
            continue
        tool = document.get("tool", {}) if isinstance(document.get("tool"), dict) else {}
        pytest_options = tool.get("pytest", {}).get("ini_options", tool.get("pytest", {}))
        hatch = tool.get("hatch", {}).get("build", {}).get("targets", {}).get("wheel", {})
        setuptools = tool.get("setuptools", {})
        find = setuptools.get("packages", {}).get("find", {}) if isinstance(setuptools.get("packages"), dict) else {}
        candidates = [
            "src",
            *(pytest_options.get("pythonpath", []) if isinstance(pytest_options.get("pythonpath"), list) else []),
            *(tool.get("ruff", {}).get("src", []) if isinstance(tool.get("ruff", {}).get("src"), list) else []),
            *(posixpath.dirname(str(package)) for package in hatch.get("packages", []) or []),
            *(setuptools.get("package-dir", {}) or {}).values(),
            *(find.get("where", []) or []),
            ".",
        ]
        for candidate in candidates:
            root = posixpath.normpath(f"{project or '.'}/{str(candidate).strip('/') or '.'}")
            if (root == "." or root in graph.directories) and root not in found:
                found.append(root)
    return [*found, *(root for root in ("src", ".") if root not in found)]


def default_roots(repo: Path) -> list[str]:
    """pytest's `testpaths`, as a test command without paths collects them, or the whole repository."""
    pyproject = repo / "pyproject.toml"
    if pyproject.is_file():
        options = tomllib.loads(pyproject.read_text(encoding="utf-8")).get("tool", {}).get("pytest", {})
        options = options.get("ini_options", options)
        if isinstance(options.get("testpaths"), list):
            return [str(path).rstrip("/") for path in options["testpaths"]]
    return ["."]


class ResolvedLanes(BaseModel):
    """The lanes a plan uses, and where each one came from, for people reading or debugging them."""

    config: LaneConfig
    #: Lane name to the facts that define it: the job and command a root came from, or the lane file.
    sources: dict[str, list[str]]
    #: Lane name to the workflow jobs its conditions gate.
    jobs: dict[str, list[str]]
    #: Every rule in force: the built-in defaults, replaced or disabled by the lane file, and its own.
    rules: list[Rule] = Field(default_factory=lambda: effective([], []))


def infer(repo: Path, base: str, head: str, extra: dict[str, Lane] | None = None) -> ResolvedLanes:
    """Lanes read from the workflows at `head`, with the job and command behind every root.

    `extra` lanes (from an extending lane file) let a workflow with no lane conditions yet start from them.
    """
    graph = WorkflowGraph(repo, head)
    roots: dict[str, set[str]] = {}
    jobs: dict[str, set[str]] = {}
    sources: dict[str, list[str]] = {}
    for (path, name), job in graph.jobs.items():
        if not job.lanes or ALL in job.lanes:
            continue
        found: set[str] = set()
        evidence: list[str] = []
        for command, directory in graph.commands(path, name):
            for line in command.splitlines():
                if named := line_roots(line, directory, graph, repo):
                    found.update(named)
                    evidence.append(f"roots {', '.join(named)} from {path}#{name}: `{line.strip()}`")
        for lane in job.lanes:
            roots.setdefault(lane, set()).update(found)
            jobs.setdefault(lane, set()).add(f"{path}#{name}")
            sources.setdefault(lane, []).extend(evidence)
    if not roots and not extra:
        raise ValueError(
            "no job condition reads a lane from the planner: gate jobs with "
            "`fromJSON(needs.<planner>.outputs.lanes).<lane>`, or name lanes in a lane file"
        )
    lanes = {
        name: Lane(roots=sorted(roots[name]), inputs=[] if roots[name] else sorted(jobs[name]))
        for name in sorted(roots)
    }
    for name, lane in lanes.items():
        if not lane.roots:
            sources[name] = [f"no test command; selected through {', '.join(lane.inputs)}"]
    for name, lane in (extra or {}).items():
        lanes.setdefault(name, lane)
    test_roots = sorted({root for lane in lanes.values() for root in lane.roots}) or ["."]
    files = {
        line.split("\t", 1)[1]: line.split()[2]
        for line in git(repo, "ls-tree", "-r", base).splitlines()
        if "\t" in line
    }
    graph_config = ImpactConfig(module_roots=module_roots(graph), test_roots=test_roots)
    policy = policy_fingerprints(repo, GitTree(tree=base, files=files, links=[]))
    # Workflows reach lanes through the workflow graph, so only the environment defaults are global.
    config = LaneConfig(
        graph=graph_config.model_copy(update={"pytest_policy": policy}),
        lanes=lanes,
        global_inputs=list(DEFAULT_GLOBAL_INPUTS),
    )
    return ResolvedLanes(
        config=config,
        sources={name: sorted(set(values), key=values.index) for name, values in sources.items()},
        jobs={name: sorted(values) for name, values in jobs.items()},
    )


def infer_lanes(repo: Path, base: str, head: str) -> LaneConfig:
    """A lane configuration read from the workflows at `head`."""
    return infer(repo, base, head).config


#: A lane file with this key extends the workflow's lanes instead of replacing them.
EXTENDS = "extends"


def resolve(repo: Path, base: str, head: str, lane_file: Path | None) -> ResolvedLanes:
    """The lanes to plan with: inferred, a complete lane file, or inferred lanes a lane file extends.

    A file with `"extends": "workflow"` lists only what differs from the workflow: lanes it names
    replace the inferred lane of that name or add a new one, `graph` fields override the inferred
    graph's, and `global_inputs` replaces the defaults. Any other lane file is complete, as before.
    """
    if lane_file is None:
        return infer(repo, base, head)
    document = json.loads(lane_file.read_text(encoding="utf-8"))
    label = lane_file.as_posix()
    if document.get(EXTENDS) is None:
        config = LaneConfig.model_validate(document)
        return ResolvedLanes(
            config=config,
            sources={name: [f"lane file {label}"] for name in config.lanes},
            jobs={},
        )
    if document[EXTENDS] != "workflow":
        raise ValueError(f'{label}: "extends" must be "workflow"')
    unknown = set(document) - {EXTENDS, "lanes", "graph", "global_inputs", "rules", "disable_rules"}
    if unknown:
        raise ValueError(f"{label}: unknown keys {sorted(unknown)}")
    named = {name: Lane.model_validate(value) for name, value in (document.get("lanes") or {}).items()}
    inferred = infer(repo, base, head, extra=named)
    lanes = dict(inferred.config.lanes)
    sources = dict(inferred.sources)
    for name, value in (document.get("lanes") or {}).items():
        replaced = name in inferred.jobs
        lanes[name] = Lane.model_validate(value)
        sources[name] = [f"{'overridden' if replaced else 'added'} by {label}"]
    graph = inferred.config.graph.model_copy(update=document.get("graph") or {})
    roots = sorted({root for lane in lanes.values() for root in lane.roots})
    if "test_roots" not in (document.get("graph") or {}) and roots:
        graph = graph.model_copy(update={"test_roots": sorted(set(graph.test_roots) | set(roots))})
    config = LaneConfig.model_validate(
        {
            "graph": graph.model_dump(),
            "lanes": {name: lane.model_dump() for name, lane in lanes.items()},
            "global_inputs": document.get("global_inputs", inferred.config.global_inputs),
        }
    )
    rules = effective(
        [Rule.model_validate(rule) for rule in document.get("rules") or []], list(document.get("disable_rules") or [])
    )
    return ResolvedLanes(config=config, sources=sources, jobs=inferred.jobs, rules=rules)
