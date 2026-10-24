"""Dependency setup measurements without adding Python dependencies to a Bun project."""

import os
import subprocess
import sys
import time
from pathlib import Path


def output(name, value):
    with Path(os.environ["GITHUB_OUTPUT"]).open("a") as stream:
        stream.write(f"{name}={value}\n")


def main():
    mode = sys.argv[1]
    if mode == "identity":
        directory = os.environ["BUN_WORKING_DIRECTORY"]
        if not (Path(directory) / "bun.lock").is_file():
            raise ValueError("setup-cached-bun requires a committed bun.lock")
        path = subprocess.check_output(["bun", "pm", "cache"], cwd=directory, text=True).strip()
        output("path", path)
        output("prefix", os.environ["BUN_CACHE_PREFIX"])
        output("key", f"{os.environ['BUN_CACHE_PREFIX']}{os.environ['BUN_CACHE_INPUTS']}")
        output("started", time.monotonic())
    elif mode == "clock":
        now = time.monotonic()
        output("started", now)
        start = os.environ.get("CACHE_STARTED")
        if start:
            output("seconds", max(0, now - float(start)))
    elif mode == "sync":
        started = time.monotonic()
        result = subprocess.run(["bun", "install", "--frozen-lockfile"], cwd=os.environ["BUN_WORKING_DIRECTORY"])
        output("seconds", time.monotonic() - started)
        output("started", time.monotonic())
        sys.exit(result.returncode)
    else:
        raise ValueError(f"Unknown operation: {mode}")


if __name__ == "__main__":
    main()
