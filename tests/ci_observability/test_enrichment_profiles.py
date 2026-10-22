import pytest
from pydantic import JsonValue

from ci_esta.ci_observability.enrichment.backend.models import PytestSnapshot
from ci_esta.ci_observability.enrichment.profiles import pytest_timings
from ci_esta.ci_observability.models import PytestTimingMetadata
from tests.ci_observability.builders import AI_TIMINGS, BACKEND_SNAPSHOT, ai_extensions, backend_extensions

MALFORMED: dict[str, JsonValue] = {"backend": {"contract_version": "not-a-backend-profile"}}
UNKNOWN_PROFILE: dict[str, JsonValue] = {"example": {"service_count": 3}}


@pytest.mark.parametrize(
    ("extensions", "expected"),
    [
        (ai_extensions(), AI_TIMINGS),
        (backend_extensions(), BACKEND_SNAPSHOT),
        (ai_extensions(timings=None), None),
        (UNKNOWN_PROFILE, None),
        (MALFORMED, None),
    ],
    ids=["ai", "backend", "ai-without-pytest", "unknown-profile", "malformed"],
)
def test_pytest_timings_come_from_whichever_profile_filled_the_extensions(
    extensions: dict[str, JsonValue], expected: PytestTimingMetadata | None
) -> None:
    assert pytest_timings(extensions) == expected


def test_backend_snapshot_is_the_shared_timing_contract_plus_counts() -> None:
    """The subclass keeps the shared fields first, so its JSON begins exactly as the timing model's."""
    shared = PytestTimingMetadata.model_validate(
        BACKEND_SNAPSHOT.model_dump(include=set(PytestTimingMetadata.model_fields))
    )

    assert isinstance(BACKEND_SNAPSHOT, PytestTimingMetadata)
    assert list(PytestSnapshot.model_fields)[: len(PytestTimingMetadata.model_fields)] == list(
        PytestTimingMetadata.model_fields
    )
    assert BACKEND_SNAPSHOT.model_dump_json().startswith(shared.model_dump_json()[:-1])
