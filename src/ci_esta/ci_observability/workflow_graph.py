"""Read workflow topology as data, without evaluating expressions or executing source code."""
import re
from collections.abc import Callable
from fnmatch import fnmatchcase


def dependencies(workflow: dict, *,
                 resolve: Callable[[str, str], dict[str, list[str]]] | None = None,
                 skipped_calls: set[str] | None = None,
                 prefix: str = "") -> dict[str, list[str]]:
    jobs = workflow.get("jobs")
    if not isinstance(jobs, dict) or not jobs:
        raise ValueError("Workflow has no jobs")
    names = {}
    for key, job in jobs.items():
        if not isinstance(job, dict):
            raise ValueError("Invalid workflow job")
        label = str(job.get("name", key))
        # Quote literal fnmatch metacharacters before inserting expression wildcards.
        parts = re.split(r"(\$\{\{.*?\}\})", label)
        label = "".join("*" if p.startswith("${{") else
                        p.replace("[", "[[]").replace("?", "[?]").replace("*", "[*]") for p in parts)
        if "strategy" in job and "${{" not in str(job.get("name", "")):
            label += "*"  # GitHub appends matrix values and omits them for a skipped matrix.
        if prefix + label in names.values():
            raise ValueError("Ambiguous job display names")
        names[key] = prefix + label
    expanded = {}
    for key, job in jobs.items():
        name = names[key]
        if "uses" not in job or any(fnmatchcase(n, name) for n in skipped_calls or set()):
            expanded[key] = {name: []}
        elif resolve is None:
            raise ValueError("Reusable workflows need an explicit expanded dependency graph")
        else:
            expanded[key] = resolve(job["uses"], name + " / ")
    graph = {}
    for key, job in jobs.items():
        needs = job.get("needs", [])
        if isinstance(needs, str):
            needs = [needs]
        if not isinstance(needs, list) or any(not isinstance(n, str) or n not in names for n in needs):
            raise ValueError(f"Unknown or dynamic prerequisites for {key}")
        parents = [name for n in needs for name in expanded[n]]
        # A reusable call starts after all outer prerequisites and completes only
        # after every inner job. Preserve its internal parallel branches.
        for name, inner_parents in expanded[key].items():
            if name in graph:
                raise ValueError("Ambiguous expanded job names")
            graph[name] = inner_parents or parents
    return graph
