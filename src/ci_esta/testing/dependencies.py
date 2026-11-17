"""The portable pytest-selective declaration format, shared by language adapters."""

from pathlib import Path

from pytest_selective_declarations import dependency_edges, is_declaration


def declared_edges(repo: Path, files: set[str]) -> dict[str, set[str]]:
    """Read declarations from the adapter's checked-out, tracked input snapshot."""
    return dependency_edges(
        {path: (repo / path).read_bytes() for path in files if is_declaration(path)},
        files,
        revision=str(repo),
    )
