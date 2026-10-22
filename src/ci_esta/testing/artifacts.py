"""
Validate CI artifact collections before deriving test decisions from them.
"""

from __future__ import annotations

from pathlib import Path


def find_artifacts(directory: Path, pattern: str) -> list[Path]:
    """
    Return matching artifact files in deterministic order.
    """
    return sorted(path for path in directory.glob(pattern) if path.is_file())


def matching_artifacts(directory: Path, pattern: str, expected_count: int, label: str) -> list[Path]:
    """
    Return a deterministic, complete artifact set or fail closed.
    """
    artifacts = find_artifacts(directory, pattern)
    if len(artifacts) != expected_count:
        raise ValueError(f"expected {expected_count} {label} artifacts, found {len(artifacts)}")
    return artifacts
