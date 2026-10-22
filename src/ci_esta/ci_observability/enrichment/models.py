"""Models shared by every enrichment profile."""

from __future__ import annotations

from ci_esta.ci_observability.models import PytestTimingMetadata, RepositorySignalV1

# Both consumers redefined the shared report's repository-signal shape
# field-for-field; the report model is the single authority.
RepositorySignal = RepositorySignalV1

# The report's test-selection section reads the timings profiles capture, so the report model
# owns them; profiles keep importing them from here.
__all__ = ["PytestTimingMetadata", "RepositorySignal"]
