"""Promote observed-only timings from the last validation admitted before merge.

GitHub's merged PR and exact attempt records are the durable pending queue. A
collector can restart or miss a notification without choosing a different source.
Timing promotion never creates a completion receipt or skips validation.
"""

from __future__ import annotations

import hashlib
import math
from datetime import datetime
from pathlib import PurePosixPath
from typing import Literal, Self

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from ci_esta.ci_observability.github import GitHubActionsClient
from ci_esta.ci_observability.models import GitHubPRDetailsV1, GitHubRunV1
from ci_esta.measurements import MeasurementIdentity
from ci_esta.testing.timing_history import merge_observations
from ci_esta.testing.timing_store import ImportedTimingSource, TimingHistory, observation_stamp


class TimingMeasurements(BaseModel):
    """One shard's fresh measurements. Never an exported retained-history file.

The producer declares whole-file coverage and exact report count. Each shard
must be measured in this attempt; retained reports need separate provenance and
are deliberately not accepted by this version of the wire contract.
"""

    model_config = ConfigDict(extra="forbid", frozen=True)
    version: Literal[1] = 1
    key: str = Field(min_length=1)
    shard: str = Field(default="all", min_length=1)
    run_id: int = Field(gt=0)
    attempt: int = Field(gt=0)
    head_sha: str = Field(pattern=r"^[a-f0-9]{40}$")
    complete_files: Literal[True]
    report_count: int = Field(gt=0)
    observed_at: AwareDatetime
    durations: dict[str, float] = Field(min_length=1)
    origin: MeasurementIdentity | None = None
    pull_request: int | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def validate_costs(self) -> Self:
        for name, seconds in self.durations.items():
            path = PurePosixPath(name)
            if (not name or path.is_absolute() or ".." in path.parts or ":" in name or "\\" in name
                    or any(ord(char) < 32 for char in name) or path.suffix != ".py"
                    or not math.isfinite(seconds) or seconds < 0):
                raise ValueError("measurements require safe relative Python files and finite nonnegative costs")
        return self


def measurement_name(key: str, shard: str, run_id: int, attempt: int) -> str:
    identity = hashlib.sha256(f"{key}\0{shard}".encode()).hexdigest()[:32]
    return f"ci-esta-measured-v1-{identity}-{run_id}-{attempt}"


def automatic_name(key: str, publisher: str = "") -> str:
    prefix = "ci-esta-observed-v1-" + hashlib.sha256(key.encode()).hexdigest()[:32] + "-"
    return prefix + hashlib.sha256(publisher.encode()).hexdigest()[:32] if publisher else prefix


class PromotionPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    repository: str = Field(pattern=r"^[^/]+/[^/]+$")
    branch: str = "main"
    workflow: str = Field(pattern=r"^[A-Za-z0-9_.-]+\.ya?ml$")
    key: str = Field(min_length=1)
    gates: set[str] = Field(default_factory=set)
    automatic: bool = False
    # Explicit expected reports per shard prevents an incomplete glob becoming a baseline.
    shards: dict[str, int] = Field(default_factory=lambda: {"all": 1}, min_length=1)

    @model_validator(mode="after")
    def positive_counts(self) -> Self:
        if not self.automatic and not self.gates:
            raise ValueError("explicit promotion requires configured gates")
        if any(not shard or count < 1 for shard, count in self.shards.items()):
            raise ValueError("each shard needs a name and positive report count")
        return self


class TimingPromotion(BaseModel):
    """Validated local staging. Safe to publish after the remote artifact expires."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    identity: str
    pull_request: GitHubPRDetailsV1
    source: GitHubRunV1
    measurements: list[TimingMeasurements]
    artifact_ids: set[int]


class PromotionDecision(BaseModel):
    status: Literal["pending", "rejected", "ready"]
    reason: str
    promotion: TimingPromotion | None = None


class MergedPRTimingCollector:
    """Fetch and validate remote evidence; publication uses the shared timing store."""

    def __init__(self, client: GitHubActionsClient, policy: PromotionPolicy) -> None:
        self.client = client
        self.policy = policy

    def select_source(self, pr: GitHubPRDetailsV1) -> GitHubRunV1 | None:
        if (pr.merged_at is None or not pr.merge_commit_sha or pr.base.ref != self.policy.branch
                or pr.base.repo is None or pr.head.repo is None
                or pr.base.repo.full_name != self.policy.repository
                or pr.head.repo.full_name != self.policy.repository):
            return None
        attempts: list[tuple[datetime, GitHubRunV1]] = []
        for run in self.client.runs_for_head(self.policy.workflow, pr.head.sha):
            if run.head_sha != pr.head.sha or run.event != "pull_request":
                raise ValueError("producer enumeration returned an unrelated run")
            if run.created_at >= pr.merged_at:
                if run.created_at == pr.merged_at:
                    raise ValueError("merge/run order ambiguous at GitHub timestamp precision")
                continue
            if run.run_attempt > 100:
                raise ValueError("attempt enumeration exceeds budget")
            for attempt in range(1, run.run_attempt + 1):
                exact = self.client.get_run(run.id, run_attempt=attempt)
                if (exact.id, exact.run_attempt, exact.head_sha, exact.event, exact.path) != (
                    run.id, attempt, pr.head.sha, "pull_request", f".github/workflows/{self.policy.workflow}"
                ):
                    raise ValueError("exact producer identity mismatch")
                # First runs are admitted at creation. GitHub exposes rerun start,
                # not a durable queue-admission timestamp; see the limitation below.
                admitted = exact.created_at if attempt == 1 else exact.run_started_at
                if admitted is None or admitted == pr.merged_at:
                    raise ValueError("attempt admission order is unavailable or ambiguous")
                if attempt > 1 and admitted > pr.merged_at:
                    # Cannot distinguish a post-merge rerun from a pre-merge queued
                    # rerun. Preserve history rather than fall back to old green.
                    raise ValueError("rerun crosses merge cutoff; queued admission cannot be reconstructed")
                if admitted < pr.merged_at:
                    attempts.append((admitted, exact))
        latest = max(attempts, key=lambda entry: (entry[0], entry[1].id, entry[1].run_attempt), default=None)
        return latest[1] if latest is not None else None

    def stage(self, number: int) -> PromotionDecision:
        pr = self.client.pull_request(number)
        source = self.select_source(pr)
        if source is None:
            return PromotionDecision(status="rejected", reason="no eligible merged same-repository source")
        jobs = self.client.list_jobs(source.id, run_attempt=source.run_attempt)
        marker = f"PR evidence #{pr.number} head {pr.head.sha}"
        owned = any(step.name == marker and step.conclusion == "success" for job in jobs for step in job.steps)
        if not self.policy.automatic and not owned:
            return PromotionDecision(status="rejected", reason="missing successful PR ownership marker")
        assert pr.merged_at is not None
        required_jobs = []
        if self.policy.automatic:
            # Without adopter-supplied gate names, require the entire producer
            # to have finished green before merge. Skipped jobs teach no costs.
            if source.updated_at is None or source.updated_at >= pr.merged_at:
                return PromotionDecision(status="rejected", reason="automatic producer completion not proven before merge")
            if not jobs or any(job.conclusion not in {"success", "skipped"} for job in jobs):
                return PromotionDecision(status="rejected", reason="automatic producer jobs are not all green")
            required_jobs = [job for job in jobs if job.conclusion == "success"]
            if not required_jobs:
                return PromotionDecision(status="rejected", reason="automatic producer executed no successful job")
        for gate in self.policy.gates:
            gate_jobs = [job for job in jobs if job.name == gate]
            if len(gate_jobs) != 1:
                return PromotionDecision(status="rejected", reason=f"gate {gate!r} missing or ambiguous")
            required_jobs.extend(gate_jobs)
        for job in required_jobs:
            if (job.conclusion != "success" or job.run_attempt != source.run_attempt
                    or job.completed_at is None or job.completed_at >= pr.merged_at):
                return PromotionDecision(status="rejected", reason=f"gate {job.name!r} not proven green before merge")
        if source.status != "completed":
            return PromotionDecision(status="pending", reason="sealed producer still running")
        if source.conclusion != "success":
            return PromotionDecision(status="rejected", reason="sealed producer did not succeed")
        artifacts = self.client.list_artifacts(None, run_id=source.id)
        measurements: list[TimingMeasurements] = []
        artifact_ids: set[int] = set()
        files: set[str] = set()
        expected = self.policy.shards
        if self.policy.automatic:
            expected = {artifact.name: 0 for artifact in artifacts
                        if artifact.name.startswith(automatic_name(self.policy.key))}
        for identifier, report_count in expected.items():
            shard = identifier
            name = identifier if self.policy.automatic else measurement_name(
                self.policy.key, shard, source.id, source.run_attempt)
            shard_artifacts = [artifact for artifact in artifacts if artifact.name == name]
            if not shard_artifacts:
                return PromotionDecision(status="pending", reason=f"shard {shard!r} unavailable or expired")
            if len(shard_artifacts) != 1 or not shard_artifacts[0].from_same_repository:
                return PromotionDecision(status="rejected", reason="ambiguous or foreign artifact")
            artifact = shard_artifacts[0]
            assert artifact.workflow_run is not None
            if artifact.workflow_run.id != source.id:
                raise ValueError("artifact source run mismatch")
            measured = TimingMeasurements.model_validate_json(self.client.read_single_file_artifact(artifact.id))
            if self.policy.automatic:
                # Retained artifacts from older attempts are never re-dated or
                # used as fallback. Only freshly executed complete files teach.
                if measured.attempt != source.run_attempt:
                    continue
                origin = MeasurementIdentity(run_id=source.id, run_attempt=source.run_attempt,
                                             head_sha=source.head_sha)
                if measured.origin != origin or measured.pull_request != pr.number:
                    return PromotionDecision(status="rejected", reason="missing or mismatched pytest execution origin")
                shard, report_count = measured.shard, measured.report_count
            # Preserve source time. Publication/download time cannot refresh stale data.
            if (measured.key, measured.shard, measured.run_id, measured.attempt, measured.head_sha,
                measured.report_count, measured.observed_at) != (
                self.policy.key, shard, source.id, source.run_attempt, source.head_sha,
                report_count, source.created_at
            ):
                return PromotionDecision(status="rejected", reason="measurement provenance or report count mismatch")
            if files.intersection(measured.durations):
                return PromotionDecision(status="rejected", reason="shards overlap at the complete-file boundary")
            files.update(measured.durations)
            measurements.append(measured)
            artifact_ids.add(artifact.id)
        if not measurements:
            return PromotionDecision(status="pending", reason="no fresh complete-file observations")
        identity = f"{self.policy.repository}/{pr.number}/{pr.head.sha}/{source.id}/{source.run_attempt}/{self.policy.key}"
        return PromotionDecision(status="ready", reason="last merged validation admitted", promotion=TimingPromotion(
            identity=identity, pull_request=pr, source=source, measurements=measurements, artifact_ids=artifact_ids,
        ))


def publish_promotion(state: TimingHistory, promotion: TimingPromotion) -> TimingHistory:
    """Return a checkpoint contribution without mutating the caller on rejection.

Idempotency is the existing source stamp/per-file replacement contract. Concurrent
collectors publish independent checkpoints; combine_histories reconciles them.
Inventory and uploader identity belong to the collector, never to the PR.
"""
    result = state.model_copy(deep=True)
    assert promotion.pull_request.merge_commit_sha is not None
    assert promotion.source.path is not None
    provenance = ImportedTimingSource(
        pull_request=promotion.pull_request.number, head_sha=promotion.source.head_sha,
        merge_commit_sha=promotion.pull_request.merge_commit_sha, run_id=promotion.source.id,
        attempt=promotion.source.run_attempt, artifact_ids=promotion.artifact_ids,
        workflow=promotion.source.path,
    )
    if promotion.identity in result.imports:
        if result.imports[promotion.identity] != provenance:
            raise ValueError("conflicting provenance for one immutable timing import")
        return result
    for measured in promotion.measurements:
        if measured.key != state.key:
            raise ValueError("promotion environment does not match history")
        merge_observations(result.observations, measured.durations,
                           observation_stamp(measured.observed_at, measured.run_id, measured.attempt))
    result.imports[promotion.identity] = provenance
    return result
