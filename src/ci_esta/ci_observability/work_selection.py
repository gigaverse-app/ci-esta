"""Provider-neutral work decisions. These explain admission; they never authorize a skip."""
from html import escape
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ci_esta.ci_observability import markdown


class WorkDecisionV1(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    name: str = Field(min_length=1, max_length=200)
    decision: Literal["run", "unaffected", "reused"]
    reason: str = Field(min_length=1, max_length=1000)
    receipt: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def reuse_requires_receipt(self):
        if self.decision == "reused" and not self.receipt:
            raise ValueError("a reused decision requires the matched completion receipt")
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


def render_work_selection(plan: WorkSelectionV1) -> str:
    labels = {"run": "Run requested", "unaffected": "Unaffected", "reused": "Prior validation reused"}
    lines = ["#### CI work decisions", "", f"Provider: {markdown.code(plan.provider)}.", "",
             "| Work | Decision | Why |", "| :-- | :-- | :-- |"]
    for item in plan.decisions:
        lines.append(f"| {markdown.cell(escape(item.name))} | {labels[item.decision]} | {markdown.cell(escape(item.reason))} |")
    lines.extend(["", "These are admission decisions. Required gates and job results below determine success.", ""])
    return "\n".join(lines)
