"""
Versioned data contracts for shared CI observability.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, SerializeAsAny, field_validator, model_validator

from ci_esta.ci_observability.critical_path import CriticalPathResult
from ci_esta.ci_observability.work_selection import WorkSelectionV1


class CollectionStatus(StrEnum):
    COMPLETE = "complete"
    PARTIAL = "partial"
    UNAVAILABLE = "unavailable"


class TimingStatus(StrEnum):
    COMPLETE = "complete"
    ACCRUED = "accrued"
    NOT_TIMED = "not_timed"


class GateKind(StrEnum):
    ACTIONS_JOB = "actions_job"
    COMMIT_STATUS = "commit_status"


class DirectPrerequisiteV1(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    job_id: str
    result: str
    display_name: str | None = None


class ActionsJobGateSelectorV1(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal[GateKind.ACTIONS_JOB]
    runner_name: str | None = Field(default=None, min_length=1)
    job_name: str | None = Field(default=None, min_length=1)
    display_name: str | None = None
    direct_prerequisites: list[DirectPrerequisiteV1] = Field(default_factory=list)

    @model_validator(mode="after")
    def one_identity(self) -> "ActionsJobGateSelectorV1":
        # Job display names and runner machine names are distinct GitHub API fields.
        if (self.runner_name is None) == (self.job_name is None):
            raise ValueError("Specify exactly one of job_name or runner_name")
        return self


class CommitStatusGateSelectorV1(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal[GateKind.COMMIT_STATUS]
    context: str
    display_name: str | None = None
    direct_prerequisites: list[DirectPrerequisiteV1] = Field(default_factory=list)


GateSelectorV1 = Annotated[
    ActionsJobGateSelectorV1 | CommitStatusGateSelectorV1,
    Field(discriminator="kind"),
]


class GitHubStepV1(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    number: int
    name: str
    status: str
    conclusion: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None


class GitHubJobV1(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    id: int
    name: str
    run_attempt: int = 1
    status: str
    conclusion: str | None = None
    #: When GitHub queued the job: after the jobs it needs completed.
    created_at: datetime | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    runner_name: str | None = None
    labels: list[str] = Field(default_factory=list)
    steps: list[GitHubStepV1] = Field(default_factory=list)


class GitHubReferencedWorkflowV1(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    path: str
    sha: str


class GitHubRunV1(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    id: int
    name: str
    workflow_id: int | None = None
    run_attempt: int
    event: str | None = None
    status: str
    conclusion: str | None = None
    created_at: datetime
    updated_at: datetime | None = None
    run_started_at: datetime | None = None
    head_branch: str | None = None
    head_sha: str
    path: str | None = None
    referenced_workflows: list[GitHubReferencedWorkflowV1] = Field(default_factory=list)
    pull_requests: list["GitHubPullRequestV1"] = Field(default_factory=list)


class GitHubPullRequestV1(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    number: int


class GitHubRunJobsV1(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    run: GitHubRunV1
    jobs: list[GitHubJobV1]


class GitHubCommitStatusV1(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    context: str
    state: str
    created_at: datetime
    updated_at: datetime


class ObservedStepV1(GitHubStepV1):
    """Step timestamps explain job time; they are never separately billed."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    timing_status: TimingStatus
    wall_seconds: float | None


class ObservedJobV1(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    job_id: int
    name: str
    run_attempt: int
    status: str
    conclusion: str | None
    timing_status: TimingStatus
    started_at: datetime | None
    completed_at: datetime | None
    wall_seconds: float | None
    start_offset_seconds: float | None
    end_offset_seconds: float | None
    #: When the job was queued, from the same origin; None when GitHub gave no creation time.
    queued_offset_seconds: float | None = None
    rounded_minutes: int | None
    rounding_waste_seconds: float | None
    seconds_to_save_minute: float | None
    seconds_until_next_minute: float | None
    runner_labels: list[str] = Field(default_factory=list)
    steps: list[ObservedStepV1] = Field(default_factory=list)


class ObservedGateV1(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: GateKind
    identity: str
    display_name: str
    status: str
    conclusion: str | None
    matched: bool
    observed_job_id: int | None
    completed_at: datetime | None
    elapsed_from_creation_seconds: float | None
    elapsed_from_run_start_seconds: float | None
    direct_prerequisites: list[DirectPrerequisiteV1]


class RunnerSkuRateV1(BaseModel):
    """Versioned caller-supplied price for one GitHub runner label."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    sku: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,63}$")
    runner_label: str = Field(min_length=1, max_length=128)
    usd_per_minute: Decimal = Field(ge=0)


class RunnerSkuCostV1(BaseModel):
    """Rounded usage and price attributed to one configured runner SKU."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    sku: str
    runner_label: str
    usd_per_minute: Decimal
    raw_runner_seconds: float
    estimated_rounded_runner_minutes: int
    rounding_waste_seconds: float
    estimated_cost_usd: Decimal


class RunnerCostV1(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    raw_runner_seconds: float
    estimated_rounded_runner_minutes: int
    rounding_waste_seconds: float
    billed_attempts: list[int]
    by_sku: list[RunnerSkuCostV1] = Field(default_factory=list)
    unpriced_rounded_runner_minutes: int = 0
    estimated_cost_usd: Decimal | None = None


class OverlappingRunCostV1(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    run_id: int
    head_sha: str
    conclusion: str | None
    created_at: datetime
    updated_at: datetime | None
    runner_cost: RunnerCostV1


class OverlappingRunnerCostV1(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    runs: list[OverlappingRunCostV1] = Field(default_factory=list)
    raw_runner_seconds: float = 0.0
    estimated_rounded_runner_minutes: int = 0
    rounding_waste_seconds: float = 0.0
    estimated_cost_usd: Decimal | None = None


#: The repository signal carrying pytest shards, wall and summed test time. The test-selection
#: section shows the same timings, so a sticky with one leaves this signal out.
PYTEST_TIMING_SIGNAL = "pytest_parallelism"


class RepositorySignalV1(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    key: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    label: str = Field(min_length=1, max_length=80)
    value: str = Field(min_length=1, max_length=512)


class PytestTimingMetadata(BaseModel):
    """
    Shard count plus wall/summed pytest seconds, as captured post-run.

    gigaverse-backend called this ``PytestTimingMetadata`` and gigaverse-ai
    called it ``PytestSnapshot``; the fields (and therefore the JSON) were
    identical.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    shard_count: int = Field(ge=1)
    wall_seconds: float | None = Field(default=None, ge=0)
    total_test_seconds: float | None = Field(default=None, ge=0)


class FullSuiteReferenceV1(BaseModel):
    """
    A measured run of the complete default gate, the baseline a narrowed run's saving is against.

    Recorded by the reporter of a green same-repository run whose change reached every test file,
    so nothing forced the full suite (coverage, a schedule, a label). Read back as the median of
    the newest few whose suite size matches.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    timings: PytestTimingMetadata
    #: Test files the run selected, which is every test file its tree had.
    total_files: int = Field(ge=1)
    run_id: int
    head_branch: str
    recorded_at: datetime

    @model_validator(mode="after")
    def validate_measured(self) -> "FullSuiteReferenceV1":
        if not self.timings.wall_seconds or not self.timings.total_test_seconds:
            raise ValueError("a full-suite reference needs measured wall and summed test time")
        return self

    @property
    def test_seconds(self) -> float:
        assert self.timings.total_test_seconds is not None, "validated on construction"
        return self.timings.total_test_seconds

    @property
    def wall_seconds(self) -> float:
        assert self.timings.wall_seconds is not None, "validated on construction"
        return self.timings.wall_seconds


class SkippedLaneReferenceV1(BaseModel):
    """What the jobs a run skipped took on the default branch's last run that executed them all."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    run_id: int
    head_branch: str
    #: Reference job names whose family this run skipped, as GitHub names them.
    jobs: list[str] = Field(min_length=1)
    runner_seconds: float = Field(ge=0)


class RunProvenanceV1(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    repository: str
    workflow_name: str | None
    run_id: int
    run_attempt: int
    head_sha: str
    pull_request_number: int | None
    workflow_created_at: datetime | None
    workflow_run_started_at: datetime | None
    observed_at: datetime


class StickySnapshotV1(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    run_id: int
    run_attempt: int
    completed_gates: int
    observed_at: datetime

    def supersedes(self, other: "StickySnapshotV1") -> bool:
        return (
            self.run_id,
            self.run_attempt,
            self.completed_gates,
            self.observed_at,
        ) > (
            other.run_id,
            other.run_attempt,
            other.completed_gates,
            other.observed_at,
        )


class CiObservabilityReportV1(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["ci-observability/v1"] = "ci-observability/v1"
    collection_status: CollectionStatus
    collection_errors: list[str] = Field(default_factory=list)
    provenance: RunProvenanceV1
    latest_attempt_jobs: list[ObservedJobV1]
    billing_jobs: list[ObservedJobV1]
    required_gates: list[ObservedGateV1]
    merge_ready_from_creation_seconds: float | None
    merge_ready_from_run_start_seconds: float | None
    workflow_initial_queue_seconds: float | None
    workflow_job_admission_delay_seconds: float | None = None
    merge_ready_after_job_admission_seconds: float | None = None
    longest_latest_job_name: str | None
    longest_latest_job_seconds: float | None
    runner_cost: RunnerCostV1
    overlapping_prior_runner_cost: OverlappingRunnerCostV1 = Field(default_factory=OverlappingRunnerCostV1)
    repository_signals: list[RepositorySignalV1] = Field(default_factory=list, max_length=32)
    extensions: dict[str, JsonValue] = Field(default_factory=dict)
    #: Only on reports that post the sticky, and only when the run uploaded a selection explanation.
    test_selection: SerializeAsAny[BaseModel] | dict[str, JsonValue] | None = None
    #: Only when the run uploaded a pytest-selective lane plan.
    lane_selection: SerializeAsAny[BaseModel] | dict[str, JsonValue] | None = None
    work_selection: WorkSelectionV1 | None = None
    critical_path: CriticalPathResult | None = None

    @property
    def attempt_elapsed_seconds(self) -> float | None:
        """Gate latency for this attempt; retain literal creation metrics separately."""
        if self.provenance.run_attempt > 1:
            return self.merge_ready_from_run_start_seconds
        return self.merge_ready_from_creation_seconds

    @field_validator("test_selection", "lane_selection", mode="before")
    @classmethod
    def validate_optional_selection(cls, value, info):
        if value is None:
            return None
        from ci_esta.ci_observability.optional_selection import validate_legacy_section
        return validate_legacy_section(info.field_name, value)

    @model_validator(mode="after")
    def validate_status_errors(self) -> "CiObservabilityReportV1":
        if self.collection_status == CollectionStatus.COMPLETE and self.collection_errors:
            raise ValueError("complete reports cannot contain collection errors")
        if self.collection_status != CollectionStatus.COMPLETE and not self.collection_errors:
            raise ValueError("partial or unavailable reports require a collection error")
        if self.work_selection is not None:
            plan, source = self.work_selection, self.provenance
            if (plan.run_id, plan.run_attempt, plan.head_sha) != (source.run_id, source.run_attempt, source.head_sha):
                raise ValueError("work selection does not match report provenance")
        signal_keys = [signal.key for signal in self.repository_signals]
        if len(signal_keys) != len(set(signal_keys)):
            raise ValueError("repository signal keys must be unique")
        return self


def __getattr__(name: str):
    # Preserve existing Python consumers without importing their provider for base reporting.
    if name in {"SelectionSectionV1", "LaneSelectionSectionV1"}:
        from ci_esta.ci_observability import python_selection_models
        return getattr(python_selection_models, name)
    raise AttributeError(name)
