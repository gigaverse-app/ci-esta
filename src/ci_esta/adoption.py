"""Read-only, advisory inventory of checked-in CI adoption.

This inventories literal wiring, not execution or correctness. Remote reusable
workflows and arbitrary scripts are opaque; successful adoption needs real runs.
The output names what it found (workflows, gate candidates, matrices, pinning) so
the next step is a concrete measurement, not a generic suggestion.
"""
from __future__ import annotations

import math
import re
from pathlib import Path

import yaml
from pydantic import BaseModel, Field, ValidationError

from ci_esta.workflow_graph import prerequisites

Scalar = str | bool | int | float | None
GUIDE = "https://ci-esta.readthedocs.io/en/latest/docs/tutorials/adoption-checklist/"
PACKING_GUIDE = "https://ci-esta.readthedocs.io/en/latest/docs/pack-matrix-jobs/"
GATE_GUIDE = "https://ci-esta.readthedocs.io/en/latest/docs/selected-gates/"
PYTHON_TESTS = re.compile(r"\b(pytest|tox|nox)(?:\s|$)")
BUN_TESTS = re.compile(r"\bbun\s+test\b")
# Jobs that still run after a failed prerequisite; a gate reached only through one can miss that failure.
RUNS_AFTER_FAILURE = re.compile(r"always\(\)|!\s*cancelled\(\)|failure\(\)")
GATE_ACTIONS = ("re-actors/alls-green", "gigaverse-app/ci-esta/actions/validation-gate")
SHA_REF = re.compile(r"@[0-9a-f]{40}$")


class _Step(BaseModel):
    name: str = ""
    uses: str = ""
    run: str = ""
    inputs: dict[str, Scalar] = Field(default_factory=dict, alias="with")


class _Strategy(BaseModel):
    matrix: dict[str, object] | str | None = None


class _Job(_Step):
    name: str = ""
    needs: list[str] | str = Field(default_factory=list)
    condition: Scalar = Field(default=None, alias="if")
    strategy: _Strategy | None = None
    steps: list[_Step] = Field(default_factory=list)


class _Runs(BaseModel):
    steps: list[_Step] = Field(default_factory=list)


class _Source(BaseModel):
    name: str = ""
    jobs: dict[str, _Job] = Field(default_factory=dict)
    runs: _Runs = Field(default_factory=_Runs)


class ActionUse(BaseModel):
    """Public inventory exposes only adoption knobs, never arbitrary action inputs."""
    source: str
    uses: str
    inputs: dict[str, Scalar] = Field(default_factory=dict)


class Suggestion(BaseModel):
    id: str
    advice: str
    evidence: list[str]
    guide: str = GUIDE


class JobSummary(BaseModel):
    id: str
    #: The check name GitHub shows, which `--gate` and `required-gates-json` take.
    name: str
    needs: list[str] = Field(default_factory=list)
    #: Concrete matrix combinations, or None when the matrix is computed at run time.
    matrix_size: int | None = None
    matrix: bool = False
    test_commands: list[str] = Field(default_factory=list)
    #: `if: always()`, `!cancelled()` or `failure()`: the job runs, and can succeed, after a prerequisite failed.
    runs_after_failure: bool = False
    gate_candidate: bool = False


class WorkflowSummary(BaseModel):
    source: str
    name: str
    triggers: list[str] = Field(default_factory=list)
    jobs: list[JobSummary] = Field(default_factory=list)
    #: Job IDs neither the gate nor anything it needs depends on: a failure there cannot fail the gate.
    outside_gate: list[str] = Field(default_factory=list)

    @property
    def gates(self) -> list[JobSummary]:
        return [job for job in self.jobs if job.gate_candidate]

    @property
    def runs_tests(self) -> bool:
        return any(job.test_commands for job in self.jobs)


class AdoptionReport(BaseModel):
    files: list[str] = Field(default_factory=list)
    actions: list[ActionUse] = Field(default_factory=list)
    workflows: list[WorkflowSummary] = Field(default_factory=list)
    suggestions: list[Suggestion] = Field(default_factory=list)
    retention: str = "no shared history-key found"
    pinning: str = "no external actions found"
    project_files: list[str] = Field(default_factory=list)
    next_steps: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


def _triggers(raw: dict) -> list[str]:
    # YAML 1.1 reads the bare key `on` as boolean true.
    events = raw.get("on", raw.get(True))
    if isinstance(events, str):
        return [events]
    return [str(event) for event in events] if isinstance(events, (list, dict)) else []


def _matrix_size(matrix: dict[str, object] | str | None) -> int | None:
    if not isinstance(matrix, dict):
        return None
    axes = [values for key, values in matrix.items() if key not in {"include", "exclude"}]
    if not all(isinstance(values, list) for values in axes):
        return None
    include, exclude = matrix.get("include", []), matrix.get("exclude", [])
    if not isinstance(include, list) or not isinstance(exclude, list):
        return None
    combinations = math.prod(len(values) for values in axes) if axes else 0
    # Includes that match an existing combination extend it rather than adding one; this is an upper bound.
    return max(combinations - len(exclude), 0) + len(include)


def _summarize(source: str, parsed: _Source, raw: dict) -> WorkflowSummary:
    jobs = []
    for job_id, job in parsed.jobs.items():
        needs = [job.needs] if isinstance(job.needs, str) else list(job.needs)
        commands = [command for step in job.steps if step.run for command in PYTHON_TESTS.findall(step.run)]
        commands += ["bun test" for step in job.steps if BUN_TESTS.search(step.run)]
        aggregates = any(step.uses.startswith(GATE_ACTIONS) for step in job.steps)
        after_failure = bool(RUNS_AFTER_FAILURE.search(str(job.condition or "")))
        matrix = job.strategy.matrix if job.strategy else None
        jobs.append(JobSummary(
            id=job_id, name=job.name or job_id, needs=needs, matrix=matrix is not None,
            matrix_size=_matrix_size(matrix), test_commands=sorted(set(commands)), runs_after_failure=after_failure,
            gate_candidate=aggregates or (after_failure and len(needs) >= 2),
        ))
    summary = WorkflowSummary(source=source, name=parsed.name or source, triggers=_triggers(raw), jobs=jobs)
    if summary.gates:
        reached = prerequisites({job.id: job.needs for job in jobs}, [gate.id for gate in summary.gates])
        summary.outside_gate = [job.id for job in jobs if job.id not in reached]
    return summary


def _inventory(root: Path) -> tuple[AdoptionReport, list[tuple[str, str]], list[tuple[str, str]]]:
    root = root.resolve()
    report = AdoptionReport()
    commands: list[tuple[str, str]] = []
    # Top-level job step names only: the jobs API, which evidence reuse reads, does not expose composite steps.
    job_steps: list[tuple[str, str]] = []
    visited: set[Path] = set()

    def visit(path: Path, workflow: bool) -> None:
        path = path.resolve()
        if not path.is_relative_to(root):
            report.limitations.append("Local reference outside the repository was not followed")
            return
        if path in visited:
            return
        visited.add(path)
        source = path.relative_to(root).as_posix()
        report.files.append(source)
        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8"))
            parsed = _Source.model_validate(raw)
        except (OSError, ValueError, yaml.YAMLError, ValidationError):
            report.limitations.append(f"Could not inspect {source}; review it manually")
            return
        if workflow:
            report.workflows.append(_summarize(source, parsed, raw))
        steps = [*parsed.runs.steps]
        for job in parsed.jobs.values():
            steps.extend([job, *job.steps])
            job_steps.extend((source, step.name) for step in job.steps if step.name)
        for step in steps:
            if step.run:
                commands.append((source, step.run))
            if not step.uses:
                continue
            report.actions.append(ActionUse(source=source, uses=step.uses, inputs={
                name: value for name, value in step.inputs.items()
                if name in {"full", "config", "history-key", "durations", "reuse-after-merge"}
            }))
            if step.uses.startswith(("./", "$/")):
                local = root / step.uses[2:]
                if local.suffix not in {".yml", ".yaml"}:
                    local = local / ("action.yaml" if (local / "action.yaml").is_file() else "action.yml")
                visit(local, workflow=local.parent == root / ".github/workflows")
            elif "/.github/workflows/" in step.uses and not step.uses.startswith("gigaverse-app/ci-esta/"):
                report.limitations.append(f"Remote workflow not expanded: {step.uses}")

    workflows = root / ".github/workflows"
    for path in sorted([*workflows.glob("*.yml"), *workflows.glob("*.yaml")]):
        visit(path, workflow=True)
    if not report.files:
        report.limitations.append("No .github/workflows/*.yml or *.yaml files found")
    report.project_files = [
        name for name in ("uv.lock", "tox.ini", "noxfile.py", "pyproject.toml", "package.json", "bun.lock")
        if (root / name).is_file()
    ]
    return report, commands, job_steps


def _pinning(actions: list[ActionUse]) -> str:
    external = [item.uses for item in actions if not item.uses.startswith(("./", "$/", "docker://"))]
    if not external:
        return "no external actions found"
    pinned = sum(bool(SHA_REF.search(uses)) for uses in external)
    if pinned == len(external):
        return (f"all {pinned} external references are commit SHAs; pin added actions the same way "
                "(`uses: OWNER/REPO@<sha> # vX.Y.Z`, sha from `gh api repos/OWNER/REPO/commits/TAG --jq .sha`)")
    if pinned:
        return f"{pinned} of {len(external)} external references are commit SHAs; follow the repository's policy"
    return f"{len(external)} external references use tags; use `@v1` for CI-esta actions"


def _next_steps(report: AdoptionReport) -> list[str]:
    candidates = [flow for flow in report.workflows if "pull_request" in flow.triggers and flow.runs_tests] or [
        flow for flow in report.workflows if flow.runs_tests]
    steps = ["Confirm the required checks: `gh api repos/OWNER/REPO/rules/branches/DEFAULT --jq "
             "'.[] | select(.type == \"required_status_checks\")'` (rulesets) or "
             "`gh api repos/OWNER/REPO/branches/DEFAULT/protection/required_status_checks --jq .contexts`."]
    if not candidates:
        steps.append("No workflow runs pytest, tox, nox or bun test; measure your main workflow's latest run.")
        return steps
    flow = max(candidates, key=lambda item: (bool(item.gates), len(item.jobs)))
    gate = f" --gate '{flow.gates[0].name}'" if flow.gates else ""
    steps.append(
        f"Measure the latest successful run of {flow.source} (export GH_TOKEN=\"$(gh auth token)\"): "
        f"`gh run list --repo OWNER/REPO --workflow {Path(flow.source).name} --status success --limit 1 "
        f"--json databaseId --jq '.[0].databaseId'`, then "
        f"`ci-esta report --repository OWNER/REPO --run-id RUN_ID{gate} --critical-path --output-dir ci-esta-report`."
    )
    if not flow.gates:
        steps.append(f"{flow.source} has no aggregate job; name the required job with --gate, or add a "
                     "validation gate before optimizing so skipped or failed work cannot pass.")
    return steps


def inspect(root: Path, *, ignore: set[str] | None = None) -> AdoptionReport:
    report, commands, job_steps = _inventory(root)

    def uses(*names: str) -> list[ActionUse]:
        return [item for item in report.actions if item.uses.split("@", 1)[0] in names]

    def ci(*names: str) -> list[ActionUse]:
        return uses(*(f"gigaverse-app/ci-esta/actions/{name}" for name in names))

    def advise(id: str, advice: str, sources: list[str], guide: str = GUIDE) -> None:
        if id not in (ignore or set()):
            report.suggestions.append(Suggestion(id=id, advice=advice, evidence=sorted(set(sources)), guide=guide))

    file_selectors = uses("gigaverse-app/pytest-selective", "gigaverse-app/pytest-selective/actions/test-impact",
                          "gigaverse-app/ci-esta/actions/test-impact")
    selectors = [*file_selectors, *uses("gigaverse-app/pytest-selective/actions/plan-lanes")]
    copied = [item.source for item in [*selectors, *ci("run-bun-tests")] if "github." in str(item.inputs.get("full", ""))]
    if copied:
        advise("checkpoint-policy", "Review the copied full-run policy. Prefer the selector's auto default when equivalent; preserve coverage or manual-experiment overrides.", copied)
    python = [path for path, command in commands if PYTHON_TESTS.search(command)]
    bun = [path for path, command in commands if BUN_TESTS.search(command)]
    if python and not selectors:
        advise("python-selection", "No shared Python selector call found. Consider file selection before collection or whole-lane selection before provisioning services; inspect existing scripts first. Measure first: selection pays only when tests, not setup, dominate the critical path.", python)
    if bun and not ci("run-bun-tests", "report-bun-tests"):
        advise("bun-reporting", "Consider run-bun-tests for selection and evidence, or report-bun-tests around an existing executor. Keep the project's Bun runner and policy.", bun)
    for flow in report.workflows:
        by_id = {job.id: job for job in flow.jobs}
        for gate in flow.gates:
            for need in gate.needs:
                prerequisite = by_id.get(need)
                if prerequisite is None or not prerequisite.runs_after_failure:
                    continue
                hidden = [job for job in prerequisite.needs if job not in gate.needs]
                if hidden:
                    advise("gate-indirect", f"{flow.source}: gate '{gate.name}' reaches {', '.join(hidden)} only through "
                           f"'{need}', which runs after failures; a failure in {', '.join(hidden)} may leave the gate "
                           f"green. Add {', '.join(hidden)} to the gate's needs and prove it with a failing probe.",
                           [flow.source], GATE_GUIDE)
        for job in flow.jobs:
            if job.test_commands and job.matrix and (job.matrix_size is None or job.matrix_size >= 3):
                size = "a run-time matrix" if job.matrix_size is None else f"{job.matrix_size} matrix jobs"
                advise("matrix-setup", f"{flow.source}: '{job.id}' runs {', '.join(job.test_commands)} in {size}. "
                       "If the report shows per-job setup comparable to test time, pack several matrix entries per "
                       "runner with plan-runner-pools.", [flow.source], PACKING_GUIDE)
    if report.files and not (ci("ci-observability") or uses("gigaverse-app/ci-esta/.github/workflows/report.yml")):
        observed = [flow.source for flow in report.workflows if flow.runs_tests] or report.files[:1]
        advise("reporting", "No completed-run reporter found. Measure with `ci-esta report` first (see next steps); "
               "add the observer workflow once the change can merge to the default branch.", observed)
    evidence = ci("resolve-lane-evidence")
    if evidence and not any(re.search(r"outputs\.receipt(?![a-z_-])", name) for _, name in job_steps):
        advise("reuse-receipt", "resolve-lane-evidence is wired, but no job step is named after its receipt output. Without a final successful step named with the receipt, no run can ever be reused.", [item.source for item in evidence])
    after_merge = [item for item in evidence if str(item.inputs.get("reuse-after-merge", "")).lower() == "true"]
    marker = re.compile(r"PR evidence #\$\{\{\s*github\.event\.pull_request\.number\s*\}\}")
    if after_merge and not any(marker.search(name) for _, name in job_steps):
        advise("reuse-ownership-marker", "Reuse after a merge is enabled, but no top-level job step is named 'PR evidence #<number> head <sha>'. GitHub often omits a run's pull request, and without the marker the push after a merge rejects every PR run and reruns all lanes.", [item.source for item in after_merge])
    learned = ci("learn-test-timings")
    restored = ci("restore-test-timings")
    if learned and not restored and (ci("plan-pytest-shards", "plan-runner-pools") or file_selectors):
        advise("timing-feedback", "Timing collection and file planning are present, but no shared restore was found. Inspect existing caches. Opt into retained history only for compatible complete-file observations, then restore before planning.", [item.source for item in learned])
    writers = [item for item in learned if item.inputs.get("history-key")]
    readers = [item for item in restored if item.inputs.get("history-key")]
    if writers or readers:
        report.retention = "configured; verify lane keys and trusted writers"
    if writers and not readers:
        advise("history-restore", "History learning is configured without a shared reader. Restore the same lane key before planning, or document the external consumer. Retention stays opt-in.", [item.source for item in writers])
    if readers and not writers:
        advise("history-writer", "History restore is configured without a shared writer. Verify a trusted producer exists for this lane; a read-only consumer may be intentional.", [item.source for item in readers])
    report.pinning = _pinning(report.actions)
    report.next_steps = _next_steps(report)
    report.limitations.append("Static wiring only: expressions, scripts and remote actions are not executed. Presence does not prove successful runs, equivalent lane keys, cache hits or savings. Required checks live in repository settings, not in workflow files.")
    return report


def render(report: AdoptionReport) -> str:
    lines = [f"Inspected {len(report.files)} local workflow/action files; timing retention: {report.retention}."]
    lines.append(f"Action pinning: {report.pinning}.")
    if report.project_files:
        note = "" if "uv.lock" in report.project_files else (
            " No uv.lock: setup-cached-uv needs one; keep the existing Python setup or use astral-sh/setup-uv caching.")
        lines.append(f"Project files: {', '.join(report.project_files)}.{note}")
    if report.workflows:
        lines.append("Workflows:")
    for flow in report.workflows:
        gates = ", ".join(f"'{gate.name}'" for gate in flow.gates) or "none found"
        lines.append(f"- {flow.source} ({flow.name}; {', '.join(flow.triggers) or 'no triggers'}): "
                     f"{len(flow.jobs)} job{'' if len(flow.jobs) == 1 else 's'}; aggregate gate: {gates}")
        for job in flow.jobs:
            facts = []
            if job.matrix:
                facts.append("run-time matrix" if job.matrix_size is None else f"matrix of {job.matrix_size}")
            if job.test_commands:
                facts.append("runs " + ", ".join(job.test_commands))
            if facts:
                lines.append(f"  {job.id}: {'; '.join(facts)}")
        if flow.outside_gate:
            lines.append(f"  not behind the gate: {', '.join(flow.outside_gate)}")
    if report.suggestions:
        lines.append("Suggestions:")
    lines.extend(f"- {item.id}: {item.advice}\n  Evidence: {', '.join(item.evidence)}\n  Guide: {item.guide}" for item in report.suggestions)
    if not report.suggestions:
        lines.append("No suggestions from these checks. Review the full adoption checklist for uninspected capabilities.")
    if report.next_steps:
        lines.append("Next steps:")
        lines.extend(f"{index}. {step}" for index, step in enumerate(report.next_steps, start=1))
    lines.extend(f"Note: {item}" for item in report.limitations)
    return "\n".join(lines)
