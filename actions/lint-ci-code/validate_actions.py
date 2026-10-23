#!/usr/bin/env python3
"""Extract and ShellCheck shell embedded in composite actions."""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

EXPRESSION = re.compile(r"\$\{\{.*?\}\}", re.DOTALL)


def embedded_shell_blocks(path: Path) -> list[tuple[str, str]]:
    """Return Bash and POSIX shell blocks from formally validated metadata."""
    data = yaml.safe_load(path.read_text())
    if not isinstance(data, dict):
        raise ValueError(f"{path}: action metadata must be a mapping")
    runs = data.get("runs")
    if not isinstance(runs, dict) or runs.get("using") != "composite":
        return []
    steps = runs.get("steps", [])

    shell_blocks: list[tuple[str, str]] = []
    for step in steps:
        if isinstance(step, dict) and isinstance(step.get("run"), str):
            shell = step.get("shell")
            shell_name = shell.split()[0] if isinstance(shell, str) else ""
            if shell_name in {"bash", "sh"}:
                shell_blocks.append((shell_name, step["run"]))
    return shell_blocks


def shellcheck(path: Path, blocks: list[tuple[str, str]]) -> None:
    """Run ShellCheck against action-embedded Bash and POSIX shell."""
    for index, (shell, block) in enumerate(blocks, start=1):
        sanitized = EXPRESSION.sub("GHA_EXPRESSION", block)
        with tempfile.NamedTemporaryFile("w", suffix=".sh") as script:
            script.write(sanitized)
            script.flush()
            result = subprocess.run(
                ["shellcheck", "--shell", shell, "--format", "gcc", script.name],
                check=False,
                capture_output=True,
                text=True,
            )
        if result.returncode:
            diagnostics = result.stdout.replace(script.name, f"{path} (run block {index})")
            raise ValueError(diagnostics.rstrip())


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("files", nargs="+", type=Path)
    args = parser.parse_args()
    try:
        for path in args.files:
            shellcheck(path, embedded_shell_blocks(path))
    except (OSError, ValueError, yaml.YAMLError) as error:
        print(error, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
