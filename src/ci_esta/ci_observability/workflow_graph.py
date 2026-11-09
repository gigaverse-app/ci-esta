"""Read workflow topology as data, without executing source code.

Job names are matched as fnmatch patterns, with every `${{ }}` expression as a
wildcard. The one expression that is evaluated is a matrix job's name built only
from `matrix.<key>`, `||` and string literals over a literal matrix: GitHub's
own expansion of that matrix gives the exact job names, so two jobs whose names
are both expressions stay distinguishable.
"""
import itertools
import re
from collections.abc import Callable
from fnmatch import fnmatchcase

EXPRESSION = re.compile(r"(\$\{\{.*?\}\})")
OPERAND = re.compile(r"\s*(?:matrix\.([A-Za-z_][\w-]*)|'((?:[^']|'')*)')\s*")


def _escape(text: str) -> str:
    """Quote literal fnmatch metacharacters."""
    return text.replace("[", "[[]").replace("?", "[?]").replace("*", "[*]")


def _matrix_combinations(matrix: object) -> list[dict] | None:
    """GitHub's expansion of a literal matrix; None when any part is computed at run time."""
    if not isinstance(matrix, dict) or "${{" in str(matrix):
        return None
    include, exclude = matrix.get("include", []), matrix.get("exclude", [])
    axes = {key: values for key, values in matrix.items() if key not in {"include", "exclude"}}
    if not isinstance(include, list) or not isinstance(exclude, list) or not all(
            isinstance(values, list) and values for values in axes.values()) or not all(
            isinstance(entry, dict) for entry in [*include, *exclude]):
        return None
    combinations = [dict(zip(axes, values)) for values in itertools.product(*axes.values())] if axes else []
    combinations = [combination for combination in combinations
                    if not any(all(combination.get(key) == value for key, value in entry.items())
                               for entry in exclude)]
    originals = list(combinations)
    for entry in include:
        # An include extends every original combination it does not contradict, or else adds its own.
        extended = [combination for combination in originals
                    if all(combination[key] == value for key, value in entry.items() if key in axes)]
        for combination in extended:
            combination.update(entry)
        if not extended:
            combinations.append(dict(entry))
    return combinations or None


def _text(value: object) -> str | None:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value) if isinstance(value, (str, int, float)) else None


def _evaluate(name: str, combination: dict) -> str | None:
    """Evaluate `matrix.<key>`, string literals and `||`; None for any other expression."""
    rendered = []
    for part in EXPRESSION.split(name):
        if not part.startswith("${{"):
            rendered.append(part)
            continue
        operands = part[3:-2].split("||")
        values = []
        for operand in operands:
            match = OPERAND.fullmatch(operand)
            if match is None:
                return None
            values.append(combination.get(match[1]) if match[1] else match[2].replace("''", "'"))
        # `a || b` yields the first truthy operand, otherwise the last one.
        value = next((value for value in values if value not in (None, False, 0, "")), values[-1])
        text = _text(value)
        if text is None:
            return None
        rendered.append(text)
    return "".join(rendered)


def _labels(key: str, job: dict, prefix: str, skipped: set[str]) -> list[str]:
    raw = str(job.get("name", key))
    label = prefix + "".join("*" if part.startswith("${{") else _escape(part) for part in EXPRESSION.split(raw))
    if "strategy" not in job:
        return [label]
    if "${{" not in raw:
        return [label + "*"]  # GitHub appends matrix values and omits them for a skipped matrix.
    combinations = _matrix_combinations(job["strategy"].get("matrix") if isinstance(job["strategy"], dict) else None)
    names = [_evaluate(raw, combination) for combination in combinations or []]
    # A skipped matrix job keeps its unevaluated name, so keep the wildcard for it.
    if not names or None in names or "uses" in job or any(
            "${{" in name and fnmatchcase(name, label) for name in skipped):
        return [label]
    return sorted({prefix + _escape(name) for name in names})


def dependencies(workflow: dict, *,
                 resolve: Callable[[str, str], dict[str, list[str]]] | None = None,
                 skipped_calls: set[str] | None = None,
                 prefix: str = "") -> dict[str, list[str]]:
    jobs = workflow.get("jobs")
    if not isinstance(jobs, dict) or not jobs:
        raise ValueError("Workflow has no jobs")
    names: dict[str, list[str]] = {}
    owners: dict[str, str] = {}
    for key, job in jobs.items():
        if not isinstance(job, dict):
            raise ValueError("Invalid workflow job")
        names[key] = _labels(key, job, prefix, skipped_calls or set())
        for label in names[key]:
            if label in owners:
                raise ValueError(
                    f"Ambiguous job display names: jobs '{owners[label]}' and '{key}' both appear as '{label}'. "
                    "Give one a distinct literal name (for example 'Linux ${{ matrix.python }}'), or pass an "
                    "explicit graph with job-dependencies-json")
            owners[label] = key
    expanded = {}
    for key, job in jobs.items():
        name = names[key][0]
        if "uses" not in job or any(fnmatchcase(n, name) for n in skipped_calls or set()):
            expanded[key] = {label: [] for label in names[key]}
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
