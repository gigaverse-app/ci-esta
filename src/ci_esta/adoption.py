"""Read-only, advisory inventory of checked-in CI adoption.

This inventories literal wiring, not execution or correctness. Remote reusable
workflows and arbitrary scripts are opaque; successful adoption needs real runs.
"""
from __future__ import annotations

import re
from pathlib import Path

import yaml
from pydantic import BaseModel, Field, ValidationError

Scalar = str | bool | int | float | None
GUIDE = "https://ci-esta.readthedocs.io/en/latest/docs/tutorials/adoption-checklist/"


class _Step(BaseModel):
    uses: str = ""
    run: str = ""
    inputs: dict[str, Scalar] = Field(default_factory=dict, alias="with")


class _Job(_Step):
    steps: list[_Step] = Field(default_factory=list)


class _Runs(BaseModel):
    steps: list[_Step] = Field(default_factory=list)


class _Source(BaseModel):
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


class AdoptionReport(BaseModel):
    files: list[str] = Field(default_factory=list)
    actions: list[ActionUse] = Field(default_factory=list)
    suggestions: list[Suggestion] = Field(default_factory=list)
    retention: str = "no shared history-key found"
    limitations: list[str] = Field(default_factory=list)


def _inventory(root: Path) -> tuple[AdoptionReport, list[tuple[str, str]]]:
    root = root.resolve()
    report = AdoptionReport()
    commands: list[tuple[str, str]] = []
    visited: set[Path] = set()

    def visit(path: Path) -> None:
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
            parsed = _Source.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
        except (OSError, ValueError, yaml.YAMLError, ValidationError):
            report.limitations.append(f"Could not inspect {source}; review it manually")
            return
        steps = [*parsed.runs.steps]
        for job in parsed.jobs.values():
            steps.extend([job, *job.steps])
        for step in steps:
            if step.run:
                commands.append((source, step.run))
            if not step.uses:
                continue
            report.actions.append(ActionUse(source=source, uses=step.uses, inputs={
                name: value for name, value in step.inputs.items()
                if name in {"full", "config", "history-key", "durations"}
            }))
            if step.uses.startswith(("./", "$/")):
                local = root / step.uses[2:]
                if local.suffix not in {".yml", ".yaml"}:
                    local = local / ("action.yaml" if (local / "action.yaml").is_file() else "action.yml")
                visit(local)
            elif "/.github/workflows/" in step.uses and not step.uses.startswith("gigaverse-app/ci-esta/"):
                report.limitations.append(f"Remote workflow not expanded: {step.uses}")

    workflows = root / ".github/workflows"
    for path in sorted([*workflows.glob("*.yml"), *workflows.glob("*.yaml")]):
        visit(path)
    if not report.files:
        report.limitations.append("No .github/workflows/*.yml or *.yaml files found")
    return report, commands


def inspect(root: Path, *, ignore: set[str] | None = None) -> AdoptionReport:
    report, commands = _inventory(root)

    def uses(*names: str) -> list[ActionUse]:
        return [item for item in report.actions if item.uses.split("@", 1)[0] in names]

    def ci(*names: str) -> list[ActionUse]:
        return uses(*(f"gigaverse-app/ci-esta/actions/{name}" for name in names))

    def advise(id: str, advice: str, sources: list[str]) -> None:
        if id not in (ignore or set()):
            report.suggestions.append(Suggestion(id=id, advice=advice, evidence=sorted(set(sources))))

    file_selectors = uses("gigaverse-app/pytest-selective", "gigaverse-app/pytest-selective/actions/test-impact",
                          "gigaverse-app/ci-esta/actions/test-impact")
    selectors = [*file_selectors, *uses("gigaverse-app/pytest-selective/actions/plan-lanes")]
    copied = [item.source for item in selectors if "github." in str(item.inputs.get("full", ""))]
    if copied:
        advise("checkpoint-policy", "Review the copied full-run policy. Prefer the selector's auto default when equivalent; preserve coverage or manual-experiment overrides.", copied)
    python = [path for path, command in commands if re.search(r"\bpytest(?:\s|$)", command)]
    bun = [path for path, command in commands if re.search(r"\bbun\s+test\b", command)]
    if python and not selectors:
        advise("python-selection", "No shared Python selector call found. Consider file selection before collection or whole-lane selection before provisioning services; inspect existing scripts first.", python)
    if bun and not ci("run-bun-tests", "report-bun-tests"):
        advise("bun-reporting", "Consider run-bun-tests for selection and evidence, or report-bun-tests around an existing executor. Keep the project's Bun runner and policy.", bun)
    if report.files and not (ci("ci-observability") or uses("gigaverse-app/ci-esta/.github/workflows/report.yml")):
        advise("reporting", "No shared completed-run reporter found. Start with a read-only report and exact required gate names before adding execution optimizations.", report.files[:1])
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
    report.limitations.append("Static wiring only: expressions, scripts and remote actions are not executed. Presence does not prove successful runs, equivalent lane keys, cache hits or savings.")
    return report


def render(report: AdoptionReport) -> str:
    lines = [f"Inspected {len(report.files)} local workflow/action files; timing retention: {report.retention}."]
    lines.extend(f"- {item.id}: {item.advice}\n  Evidence: {', '.join(item.evidence)}\n  Guide: {item.guide}" for item in report.suggestions)
    if not report.suggestions:
        lines.append("No suggestions from these checks. Review the full adoption checklist for uninspected capabilities.")
    lines.extend(f"Note: {item}" for item in report.limitations)
    return "\n".join(lines)
