"""Lanes inferred from the workflow, so a repository needs no lane file.

The lanes are the names the workflow's job conditions read from the planner's output. A lane's test
roots are the paths its jobs pass to a test command (`pytest X`, `python -m pytest X`, `bun test X`,
`unittest discover -s X`); a test command with no path takes pytest's `testpaths`, or the whole
repository. A lane whose jobs run no test command (a build, a smoke check) is selected through the
jobs it gates. A test no lane claims still runs every lane, so a guess that misses errs toward work.

The reviewed pytest policy is taken from the base commit: a pull request that changes how pytest
collects runs every lane, as a reviewed lane file would until its fingerprints were refreshed.
"""

from __future__ import annotations

import re
import shlex
import tomllib
from pathlib import Path

from pytest_selective.ci import Lane, LaneConfig
from pytest_selective.impact_graph import policy_fingerprints
from pytest_selective.impact_models import GitTree, ImpactConfig
from pytest_selective.input_policy import DEFAULT_GLOBAL_INPUTS

from ci_esta.git import git
from ci_esta.workflow_graph import ALL, WorkflowGraph

#: The words that start a test command, and the arguments after them that are paths.
TEST_COMMAND = re.compile(
    r"(?:^|[\s;&|(])(?:uv run (?:--[\w-]+(?:[ =]\S+)? )*)?(pytest|python3? -m pytest|bun test)(?![\w-])(.*)"
)
UNITTEST = re.compile(r"python3? -m unittest discover\b.*?(?:-s|--start-directory)[ =](\S+)")
#: A repository script that runs the tests (`python scripts/run_ci_tests.py`): it collects pytest's defaults.
TEST_WRAPPER = re.compile(r"\bpython3? (?:-\S+ )*(\S*run\w*tests?\w*\.py)\b")
#: Options whose next word is a value, not a test path.
VALUED_OPTIONS = {
    "-c",
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


def paths_after(arguments: str, files: set[str], directories: set[str]) -> list[str] | None:
    """Repository paths among a test command's arguments; None when it names none."""
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
        if path in files or path in directories:
            found.append(path)
    return found or None


def default_roots(repo: Path) -> list[str]:
    """pytest's `testpaths`, as a test command without paths collects them, or the whole repository."""
    pyproject = repo / "pyproject.toml"
    if pyproject.is_file():
        options = tomllib.loads(pyproject.read_text(encoding="utf-8")).get("tool", {}).get("pytest", {})
        options = options.get("ini_options", options)
        if isinstance(options.get("testpaths"), list):
            return [str(path).rstrip("/") for path in options["testpaths"]]
    return ["."]


def infer_lanes(repo: Path, base: str, head: str) -> LaneConfig:
    """A lane configuration read from the workflows at `head`."""
    graph = WorkflowGraph(repo, head)
    directories = graph.directories
    roots: dict[str, set[str]] = {}
    jobs: dict[str, set[str]] = {}
    for (path, name), job in graph.jobs.items():
        if not job.lanes or ALL in job.lanes:
            continue
        commands = [
            str(step.get("run", ""))
            for step in graph.documents[path]["jobs"][name].get("steps", []) or []
            if isinstance(step, dict)
        ]
        found: set[str] = set()
        for command in commands:
            for line in command.splitlines():
                if match := TEST_COMMAND.search(line):
                    found.update(paths_after(match.group(2), graph.files, directories) or default_roots(repo))
                if match := UNITTEST.search(line):
                    found.add(match.group(1).removeprefix("./").rstrip("/"))
                elif (match := TEST_WRAPPER.search(line)) and match.group(1).removeprefix("./") in graph.files:
                    found.update(default_roots(repo))
        for lane in job.lanes:
            roots.setdefault(lane, set()).update(found)
            jobs.setdefault(lane, set()).add(f"{path}#{name}")
    if not roots:
        raise ValueError("no job condition reads a lane from the planner; add a lane file")
    lanes = {
        name: Lane(roots=sorted(roots[name]), inputs=[] if roots[name] else sorted(jobs[name]))
        for name in sorted(roots)
    }
    test_roots = sorted({root for lane in lanes.values() for root in lane.roots}) or ["."]
    files = {
        line.split("\t", 1)[1]: line.split()[2]
        for line in git(repo, "ls-tree", "-r", base).splitlines()
        if "\t" in line
    }
    graph_config = ImpactConfig(module_roots=["src", "."], test_roots=test_roots)
    policy = policy_fingerprints(repo, GitTree(tree=base, files=files, links=[]))
    # Workflows reach lanes through the workflow graph, so only the environment defaults are global.
    return LaneConfig(
        graph=graph_config.model_copy(update={"pytest_policy": policy}),
        lanes=lanes,
        global_inputs=list(DEFAULT_GLOBAL_INPUTS),
    )
