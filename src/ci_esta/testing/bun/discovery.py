"""One Bun test-file inventory for runtime setup and lane planning."""

from collections.abc import Iterable
from pathlib import PurePosixPath

from ci_esta.testing.bun.models import TEST_FILE


def test_files(paths: Iterable[str]) -> list[str]:
    return sorted(path for path in paths if TEST_FILE.search(PurePosixPath(path).name))
