"""Turn a missing optional dependency into an install instruction instead of a traceback.

Base reporting deliberately installs neither pytest nor pytest-selective. Commands that need them import them lazily
and run inside :func:`requires_selection`, so a base install names the extra to add rather than crashing.
"""

from __future__ import annotations

import sys
from collections.abc import Iterator
from contextlib import contextmanager

#: Root modules the ``selection`` extra (pytest-selective, which brings pytest) provides.
SELECTION_MODULES = frozenset({"pytest_selective", "pytest", "_pytest"})
SELECTION_INSTALL = "uv tool install 'ci-esta[selection]>=1.11,<2'"


@contextmanager
def requires_selection(command: str) -> Iterator[None]:
    """Exit 2 with the install command when ``command`` needs the ``selection`` extra and it is absent."""
    try:
        yield
    except ModuleNotFoundError as error:
        if (error.name or "").split(".", 1)[0] not in SELECTION_MODULES:
            raise
        print(
            f"{command} needs pytest-selective ({error.name} is not installed); the base ci-esta package does not "
            f"include it.\nInstall the selection extra: {SELECTION_INSTALL}\n"
            "In a project environment, add 'ci-esta[selection]' (or 'ci-esta[pytest]' for the pytest plugins).",
            file=sys.stderr,
        )
        raise SystemExit(2) from None
