"""Typed Python contracts preserving the public Bun adapter's JSON field names."""

import re
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, computed_field
from pydantic.alias_generators import to_camel

from ci_esta.ci_observability.work_selection import execution_is_complete
from ci_esta.measurements import MeasurementIdentity

#: A Bun test file name: what the inventory, the planner's module graph and plan-work's runtime check accept.
TEST_FILE = re.compile(r"[._](?:test|spec)\.[cm]?[jt]sx?$")

BUN_ENVIRONMENT_NAMES = ("package.json", "bun.lock", "bun.lockb", "bunfig*.toml", "tsconfig*.json", ".bun-version")
BUN_ENVIRONMENT_FILES = [pattern for name in BUN_ENVIRONMENT_NAMES for pattern in (name, f"**/{name}")]


class JsonContract(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class SelectionRequest(JsonContract):
    cwd: Path = Field(default_factory=Path.cwd)
    base: str = ""
    validated_head: str = ""
    full: bool = False
    checkpoint_reason: str | None = ""
    policy_file: str = ""
    always_run_files: list[str] = Field(default_factory=list)
    test_files: list[str] | None = None
    bun: str = "bun"
    preloads: list[str] = Field(default_factory=list)


class SelectionPlan(JsonContract):
    mode: Literal["full", "scoped", "none"] = "full"
    base: str = ""
    tested_sha: str = ""
    changed_files: list[str] = Field(default_factory=list)
    fallback: bool = False
    reason: str = "Full checkpoint requested"
    validated_head: str | None = None
    selected_files: list[str] | None = None


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
    timing_history: str | None = None


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
    selected_files: list[str] | None = None
    executed_files: list[str] | None
    executions: list[BatchExecution] = Field(default_factory=list)
    duration_ms: float | None = None
    exit_code: int
    receipt: str | None = None

    @computed_field
    @property
    def complete(self) -> bool:
        return execution_is_complete(self.mode, self.executed_files, self.total_files, self.always_run_files) and (
            self.selected_files is None or (self.executed_files is not None
                                           and set(self.selected_files).issubset(self.executed_files))
        )


class ReportContext(MeasurementIdentity):
    """Bun's published attempt field is an alias of the shared measurement identity."""
    model_config = ConfigDict(populate_by_name=True)
    run_attempt: int = Field(alias="attempt", ge=1)

    @property
    def attempt(self) -> int:
        return self.run_attempt


class DeclarationAudit(JsonContract):
    """Declarations to add, delete and merge, from one traversal of every Bun test."""

    #: Reachable modules that name untracked inputs without a declaration; selection falls back to full.
    undeclared: list[str]
    #: Declared readers no test reaches; their declarations change no selection.
    unreached: list[str]
    #: Directories holding more than one file sidecar, which one `.gv-dependencies.yaml` can replace.
    crowded: dict[str, list[str]]
