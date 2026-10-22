from ci_esta.ci_observability.enrichment.profiles import pytest_timings
from ci_esta.ci_observability.models import PytestTimingMetadata


def test_repository_neutral_timings_use_the_shared_contract() -> None:
    timings = PytestTimingMetadata(shard_count=2, wall_seconds=30, total_test_seconds=52)
    assert pytest_timings({"pytest": timings.model_dump(mode="json")}) == timings


def test_invalid_timings_leave_the_report_available() -> None:
    assert pytest_timings({"pytest": {"wall_seconds": "broken"}}) is None
