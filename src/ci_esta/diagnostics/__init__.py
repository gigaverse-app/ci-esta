"""Run a command with optional Linux host and cgroup diagnostics."""

import os
import sys
from pathlib import Path


def main() -> int:
    if not sys.argv[1:]:
        print("usage: ci-esta-resources <command> [args...]", file=sys.stderr)
        return 2
    if sys.platform != "linux":
        print("ci-esta-resources requires Linux (procfs and cgroup diagnostics)", file=sys.stderr)
        return 2
    # Replace the adapter so the shell owns command status and signal handling.
    os.execvp("bash", ["bash", str(Path(__file__).with_name("resources.sh")), *sys.argv[1:]])
    return 2
