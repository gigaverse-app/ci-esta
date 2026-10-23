"""Atomic publication for scheduling hints and retained checkpoints."""

from pathlib import Path
from tempfile import NamedTemporaryFile


def write_atomic_text(contents: str, output: Path) -> None:
    """Replace only a completed file; clean up after write, close or replace failure."""
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with NamedTemporaryFile(mode="w", encoding="utf-8", dir=output.parent, delete=False) as temporary:
            # Register cleanup before writing, including a partial write failure.
            temporary_path = Path(temporary.name)
            temporary.write(contents)
        temporary_path.replace(output)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
