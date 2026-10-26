"""Typed Python contracts preserving the public Bun adapter's JSON field names."""

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, computed_field
from pydantic.alias_generators import to_camel

from ci_esta.ci_observability.work_selection import execution_is_complete


class JsonContract(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class SelectionRequest(JsonContract):
    cwd: Path = Field(default_factory=Path.cwd)
    base: str = ""
    validated_head: str = ""
    full: bool = False
    checkpoint_reason: str | None = ""
    policy_file: str = ".github/test-selection.json"
    always_run_files: list[str] = Field(default_factory=list)


class SelectionPlan(JsonContract):
    mode: Literal["full", "scoped", "none"] = "full"
    base: str = ""
    tested_sha: str = ""
    changed_files: list[str] = Field(default_factory=list)
    fallback: bool = False
    reason: str = "Full checkpoint requested"
    validated_head: str | None = None


class Reader(JsonContract):
    model_config = ConfigDict(strict=True)
    blob: str = Field(pattern=r"^[0-9a-f]{40}$")
    inputs: list[str]


class BunPolicy(JsonContract):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, strict=True)
    schema_version: Literal["ci-esta/bun-policy/v1"] = Field(alias="schema_version")
    scoped_roots: list[str]
    unaffected_paths: list[str]
    unaffected_roots: list[str]
    source_extensions: list[str]
    runtime_roots: list[str]
    reviewed_readers: dict[str, Reader]


class Inventory(JsonContract):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, strict=True)
    schema_version: Literal["ci-esta/bun-inventory/v1"] = Field(alias="schema_version", exclude=True)
    files: list[str] = Field(min_length=1)
    always_run_files: list[str]


class RunRequest(SelectionRequest):
    inventory_file: str
    plan_file: str | None = None
    output_directory: Path
    args: list[str] = Field(default_factory=lambda: ["--isolate", "--parallel"])
    shards: int = Field(default=1, strict=True, ge=1)
    bun: str = "bun"


class BatchExecution(JsonContract):
    shard: int
    affected: bool
    exit_code: int
    duration_ms: float
    executed_files: list[str] | None
    error: str | None = None


class BunExecution(JsonContract):
    schema_version: Literal["ci-esta/bun-execution/v1"] = Field(default="ci-esta/bun-execution/v1", alias="schema_version")
    mode: Literal["full", "scoped", "none", "reused"]
    base: str = ""
    tested_sha: str
    changed_files: list[str] = Field(default_factory=list)
    fallback: bool = False
    reason: str
    validated_head: str | None = None
    bun_version: str
    cpu_count: int | None = None
    workers: int | None = None
    runner_label: str | None = None
    total_files: int
    always_run_files: list[str] = Field(default_factory=list)
    executed_files: list[str] | None
    executions: list[BatchExecution] = Field(default_factory=list)
    duration_ms: float | None = None
    exit_code: int
    receipt: str | None = None

    @computed_field
    @property
    def complete(self) -> bool:
        return execution_is_complete(self.mode, self.executed_files, self.total_files, self.always_run_files)


class ReportContext(JsonContract):
    run_id: int
    attempt: int
    head_sha: str
