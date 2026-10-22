"""Read shared facts back out of whichever consumer profile filled a report's ``extensions``."""

from pydantic import JsonValue, ValidationError

from ci_esta.ci_observability.enrichment.ai import AiExtensions
from ci_esta.ci_observability.enrichment.backend.models import BackendExtensions
from ci_esta.ci_observability.enrichment.models import PytestTimingMetadata


def pytest_timings(extensions: dict[str, JsonValue]) -> PytestTimingMetadata | None:
    """
    This run's pytest shard timings, or None when no profile recorded them.

    Each profile's extension key is part of its wire contract, so it selects the model. A
    malformed profile is None, not an error: the sticky shows the timing as unknown rather
    than losing the rest of the report.
    """
    try:
        if "pytest" in extensions:
            return PytestTimingMetadata.model_validate(extensions["pytest"])
        if "backend" in extensions:
            return BackendExtensions.model_validate(extensions).backend.pytest
        if "ai" in extensions:
            return AiExtensions.model_validate(extensions).ai.pytest
    except ValidationError:
        return None
    return None
