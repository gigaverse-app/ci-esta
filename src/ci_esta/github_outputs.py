"""Dependency-free GitHub Actions output writer, also used by standalone scripts."""
import os
from pathlib import Path
from uuid import uuid4


def append_outputs(output: str | None = None, /, **values: str | bool | int | float) -> None:
    destination = os.environ.get("GITHUB_OUTPUT", "") if output is None else output
    if not destination:
        return
    with Path(destination).open("a", encoding="utf-8") as stream:
        for key, value in values.items():
            if not key or any(character in key for character in "\r\n="):
                raise ValueError("Invalid GitHub output name")
            rendered = str(value).lower() if isinstance(value, bool) else str(value)
            if "\n" in rendered or "\r" in rendered:
                delimiter = "ci_esta_" + uuid4().hex
                stream.write(f"{key}<<{delimiter}\n{rendered}\n{delimiter}\n")
            else:
                stream.write(f"{key}={rendered}\n")
