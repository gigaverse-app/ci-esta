"""Optional pytest-selective report adapter; the provider owns its explanation models."""
from statistics import median

from pydantic import BaseModel, ConfigDict, Field
from pytest_selective.ci import LanePlan
from pytest_selective.impact_models import SelectionExplanation

from ci_esta.ci_observability.models import FullSuiteReferenceV1, PytestTimingMetadata, SkippedLaneReferenceV1


class SelectionSectionV1(BaseModel):
    """What the sticky's test-selection section is rendered from."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    explanation: SelectionExplanation
    pytest: PytestTimingMetadata | None = None
    #: Recent comparable full-suite runs, newest first; the saving is against their median.
    references: list[FullSuiteReferenceV1] = Field(default_factory=list)

    @property
    def baseline_test_seconds(self) -> float | None:
        return median(reference.test_seconds for reference in self.references) if self.references else None

    @property
    def baseline_wall_seconds(self) -> float | None:
        return median(reference.wall_seconds for reference in self.references) if self.references else None


class LaneSelectionSectionV1(BaseModel):
    """What the sticky's lane section is rendered from: a pytest-selective lane plan."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    plan: LanePlan
    #: An estimate of the work skipping avoided; None when no comparable run is available.
    reference: SkippedLaneReferenceV1 | None = None


