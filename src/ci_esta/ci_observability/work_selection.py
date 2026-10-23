"""Provider-neutral work decisions. These explain admission; they never authorize a skip."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ci_esta.ci_observability import brand, markdown


class WorkExecutionV1(BaseModel):
    """Observed runner output, separate from the admission request and benchmark evidence."""
    model_config = ConfigDict(frozen=True, extra="forbid")
    mode: Literal["full", "scoped", "none", "reused"]
    status: Literal["passed", "failed", "not_run", "incomplete"]
    total_files: int = Field(ge=0)
    executed_files: list[str] | None = Field(default=None, max_length=100000)
    always_run_files: list[str] = Field(default_factory=list, max_length=100000)
    duration_seconds: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    tested_sha: str = Field(pattern=r"^[0-9a-f]{40}$")
    base_sha: str | None = Field(default=None, pattern=r"^[0-9a-f]{40}$")
    runtime: str = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def consistent_inventory(self):
        for files in (self.executed_files, self.always_run_files):
            if files is not None and (len(set(files)) != len(files) or len(files) > self.total_files
                                      or any(not file or len(file) > 500 for file in files)):
                raise ValueError("execution inventory must be unique and within the full suite size")
        if self.mode == "reused" and (self.status != "not_run" or self.executed_files):
            raise ValueError("reused work cannot claim newly executed tests")
        if self.status == "not_run" and self.executed_files:
            raise ValueError("unexecuted work cannot contain executed files")
        if self.status == "passed" and self.executed_files is None:
            raise ValueError("passed execution needs a known inventory")
        if self.status == "passed" and self.executed_files is not None:
            if self.mode == "full" and len(self.executed_files) != self.total_files:
                raise ValueError("passed full execution must cover the inventory")
            if not set(self.always_run_files).issubset(self.executed_files):
                raise ValueError("passed execution must include always-run contracts")
        return self


class WorkDecisionV1(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    name: str = Field(min_length=1, max_length=200)
    decision: Literal["run", "unaffected", "reused"]
    reason: str = Field(min_length=1, max_length=1000)
    receipt: str | None = Field(default=None, max_length=500)
    execution: WorkExecutionV1 | None = None

    @model_validator(mode="after")
    def reuse_requires_receipt(self):
        if self.decision == "reused" and not self.receipt:
            raise ValueError("a reused decision requires the matched completion receipt")
        if self.execution is not None and (self.decision == "reused") != (self.execution.mode == "reused"):
            raise ValueError("execution and admission disagree about reuse")
        return self


class WorkSelectionV1(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    schema_version: Literal["ci-esta/work-selection/v1"] = "ci-esta/work-selection/v1"
    provider: str = Field(min_length=1, max_length=100)
    run_id: int = Field(gt=0)
    run_attempt: int = Field(gt=0)
    head_sha: str = Field(pattern=r"^[0-9a-f]{40}$")
    input_identity: str = Field(min_length=1, max_length=500)
    fallback: bool = False
    decisions: list[WorkDecisionV1] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def conservative_fallback(self):
        if len({item.name for item in self.decisions}) != len(self.decisions):
            raise ValueError("work names must be unique")
        if self.fallback and any(item.decision != "run" for item in self.decisions):
            raise ValueError("fallback must request every declared unit of work")
        return self


def badges(plan: WorkSelectionV1) -> list[brand.Badge]:
    selected, executed = brand.unavailable("selected"), brand.unavailable("executed")
    # Inventories from different work units may overlap. Do not sum their files.
    if len(plan.decisions) == 1:
        execution = plan.decisions[0].execution
        if execution is not None:
            # Full/none modes establish admission independently of success. Native
            # scoped selection has no separate selected-file inventory to report.
            if execution.mode in ("full", "none"):
                selected = brand.quantity("selected", execution.total_files if execution.mode == "full"
                                          else len(execution.always_run_files),
                                          execution.total_files, "files")
            if execution.executed_files is not None:
                executed = brand.quantity("executed", len(execution.executed_files), execution.total_files, "files")
    return [selected, executed]


def render_work_selection(plan: WorkSelectionV1) -> str:
    labels = {"run": "Run requested", "unaffected": "Unaffected", "reused": "Prior validation reused"}
    lines = ["#### CI work decisions", "", f"Provider: {markdown.code(plan.provider)}.", "",
             "| Work | Decision | Why |", "| :-- | :-- | :-- |"]
    # Preserve the full inventory in JSON while keeping the sticky below GitHub's comment limit.
    for item in plan.decisions[:20]:
        name = markdown.inline(item.name).replace("|", "\\|")
        reason = markdown.inline(item.reason[:300]).replace("|", "\\|")
        lines.append(f"| {name} | {labels[item.decision]} | {reason} |")
    if len(plan.decisions) > 20:
        lines.extend(["", f"{len(plan.decisions) - 20} additional work decisions are preserved in the JSON report."])
    lines.extend(["", "These are admission decisions. Required gates and job results below determine success.", ""])
    for item in plan.decisions[:20]:
        if item.execution is not None:
            lines.extend(_render_execution(item.name, item.execution))
    return "\n".join(lines)


def _render_execution(name: str, execution: WorkExecutionV1) -> list[str]:
    from ci_esta.ci_observability.enrichment.primitives import format_seconds

    files = execution.executed_files
    count = "unavailable" if files is None else f"{len(files)} / {execution.total_files}"
    wall = "unavailable" if execution.duration_seconds is None else format_seconds(execution.duration_seconds)
    lines = [f"#### {markdown.inline(name)}: {execution.mode}", "",
             "| Result | Files executed / full inventory | Test wall time | Runtime |",
             "| :-- | --: | --: | :-- |",
             f"| {execution.status.replace('_', ' ')} | {count} | {wall} | {markdown.cell(execution.runtime)} |", ""]
    if files is not None and execution.status == "passed" and len(files) < execution.total_files:
        lines += [f"**{execution.total_files - len(files)} test files avoided.** "
                  "File-count reduction is not a measured time saving.", ""]
    if execution.mode == "reused":
        lines += ["Prior validation reused; no tests executed in this attempt.", ""]
    lines += ["<details><summary>Test inventory and selection inputs</summary>", "",
              f"Tested commit: {markdown.code(execution.tested_sha)}. "
              f"Selection base: {markdown.code(execution.base_sha or 'not applicable')}.", "",
              f"Always-run contracts: {len(execution.always_run_files)} files.", ""]
    if files is None:
        lines += ["Execution inventory unavailable; no avoided-file claim."]
    else:
        lines += [f"- {markdown.code(file)}" for file in files[:30]]
        if len(files) > 30:
            lines += [f"{len(files) - 30} more executed files are retained in the JSON report."]
    return [*lines, "", "</details>", ""]
