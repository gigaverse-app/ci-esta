"""Read workflow topology as data, without evaluating expressions or executing source code."""
import re


def dependencies(workflow: dict) -> dict[str, list[str]]:
    jobs = workflow.get("jobs")
    if not isinstance(jobs, dict) or not jobs:
        raise ValueError("Workflow has no jobs")
    names = {}
    for key, job in jobs.items():
        if not isinstance(job, dict) or "uses" in job:
            raise ValueError("Reusable workflows need an explicit expanded dependency graph")
        label = str(job.get("name", key))
        # Quote literal fnmatch metacharacters before inserting expression wildcards.
        parts = re.split(r"(\$\{\{.*?\}\})", label)
        label = "".join("*" if p.startswith("${{") else
                        p.replace("[", "[[]").replace("?", "[?]").replace("*", "[*]") for p in parts)
        if "strategy" in job and "${{" not in str(job.get("name", "")):
            label += "*"  # GitHub appends matrix values and omits them for a skipped matrix.
        if label in names.values():
            raise ValueError("Ambiguous job display names")
        names[key] = label
    graph = {}
    for key, job in jobs.items():
        needs = job.get("needs", [])
        if isinstance(needs, str):
            needs = [needs]
        if not isinstance(needs, list) or any(not isinstance(n, str) or n not in names for n in needs):
            raise ValueError(f"Unknown or dynamic prerequisites for {key}")
        graph[names[key]] = [names[n] for n in needs]
    return graph
