"""Dependency setup measurements without adding Python dependencies to a Bun project."""

import os
import subprocess
import sys
import time
from pathlib import Path

# The helper is stdlib-only. Source actions use src; installed wheels already expose the package.
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from ci_esta.github_outputs import append_outputs


def main():
    mode = sys.argv[1]
    if mode == "identity":
        directory = os.environ["BUN_WORKING_DIRECTORY"]
        if not (Path(directory) / "bun.lock").is_file():
            raise ValueError("setup-cached-bun requires a committed bun.lock")
        path = subprocess.check_output(["bun", "pm", "cache"], cwd=directory, text=True).strip()
        append_outputs(path=path)
        append_outputs(prefix=os.environ["BUN_CACHE_PREFIX"])
        append_outputs(key=f"{os.environ['BUN_CACHE_PREFIX']}{os.environ['BUN_CACHE_INPUTS']}")
        append_outputs(started=time.monotonic())
    elif mode == "clock":
        now = time.monotonic()
        append_outputs(started=now)
        start = os.environ.get("CACHE_STARTED")
        if start:
            append_outputs(seconds=max(0, now - float(start)))
    elif mode == "sync":
        started = time.monotonic()
        result = subprocess.run(["bun", "install", "--frozen-lockfile"], cwd=os.environ["BUN_WORKING_DIRECTORY"])
        append_outputs(seconds=time.monotonic() - started)
        append_outputs(started=time.monotonic())
        sys.exit(result.returncode)
    else:
        raise ValueError(f"Unknown operation: {mode}")


if __name__ == "__main__":
    main()
