"""Locate canonical action assets from either a checkout or an installed wheel."""

from __future__ import annotations

from pathlib import Path


def source_root() -> Path:
    """Return the read-only root containing the distributed Actions and helper scripts."""
    package = Path(__file__).resolve().parent
    bundled = package / "_resources"
    if bundled.is_dir():
        return bundled
    checkout = package.parents[1]
    if (checkout / "actions").is_dir():
        return checkout
    raise FileNotFoundError("CI-esta action resources are missing; reinstall the package")
