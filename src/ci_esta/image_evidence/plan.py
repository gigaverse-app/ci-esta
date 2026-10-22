"""Resolve named pull scenarios once, before any external resources are created."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

Digest = Annotated[str, Field(pattern=r"^sha256:[a-f0-9]{64}$")]
Scenario = Annotated[str, Field(pattern=r"^[a-z][a-z0-9-]{0,39}$")]
Arm = Literal["baseline", "candidate"]


class PullInputs(BaseModel):
    repository: str = Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9.:-]*/[a-z0-9/_-]+$")
    prefix: str = Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,100}$")
    dind: str = Field(pattern=r"^[^\s]+@sha256:[a-f0-9]{64}$")
    pull_samples: int = Field(default=3, ge=1, le=20)
    architecture: Literal["amd64", "arm64"] = "amd64"
    pull_sequence: tuple[Scenario, ...] = ("cold", "source", "bump")

    @field_validator("pull_sequence")
    @classmethod
    def unique_sequence(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if not 1 <= len(value) <= 20 or len(value) != len(set(value)):
            raise ValueError("Pull sequence must contain 1-20 unique scenario names")
        return value


class ImageResult(BaseModel):
    arm: Arm
    scenario: Scenario
    sample: int = Field(ge=0)
    digest: Digest


class PullPlan(BaseModel):
    """Frozen identity snapshot shared by the Docker and node observers."""

    model_config = ConfigDict(frozen=True)
    repository: str
    prefix: str
    dind: str
    samples: int
    architecture: str
    sequence: tuple[str, ...]
    images: dict[Arm, dict[str, str]]


def prepare_pull_plan(directory: Path) -> PullPlan:
    inputs = PullInputs.model_validate_json((directory / "inputs.json").read_text())
    return resolve_plan(inputs, (directory / "results.jsonl").read_text())


def resolve_plan(inputs: PullInputs, records: str) -> PullPlan:
    results = [ImageResult.model_validate_json(line) for line in records.splitlines() if line.strip()]
    images: dict[Arm, dict[str, str]] = {}
    for arm in ("baseline", "candidate"):
        images[arm] = {}
        for scenario in inputs.pull_sequence:
            matches = [r for r in results if r.arm == arm and r.scenario == scenario and r.sample == 0]
            if len(matches) != 1:
                raise ValueError(f"Expected exactly one seed image for {arm}/{scenario}; found {len(matches)}")
            images[arm][scenario] = f"{inputs.repository}@{matches[0].digest}"
    return PullPlan(
        repository=inputs.repository,
        prefix=inputs.prefix,
        dind=inputs.dind,
        samples=inputs.pull_samples,
        architecture=inputs.architecture,
        sequence=inputs.pull_sequence,
        images=images,
    )


def prepare_sequence(directory: Path, name: str, sequence: tuple[str, ...]) -> Path:
    """Create a separately owned empty-store sequence without renaming scenarios."""
    if not name or any(character not in "abcdefghijklmnopqrstuvwxyz0123456789-" for character in name):
        raise ValueError("Sequence directory must be a simple lowercase name")
    inputs = json.loads((directory / "inputs.json").read_text())
    inputs["prefix"] += "-" + name
    inputs["pull_sequence"] = sequence
    records = (directory / "results.jsonl").read_text()
    resolve_plan(PullInputs.model_validate(inputs), records)
    output = directory / name
    output.mkdir()
    (output / "inputs.json").write_text(json.dumps(inputs, indent=2) + "\n")
    (output / "results.jsonl").write_text(records)
    return output
