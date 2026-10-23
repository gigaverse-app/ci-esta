"""Execute the planner's exact file list and retain pytest's completion evidence."""

import os
import subprocess
import sys
from pathlib import Path

index = int(os.environ["GV_PYTEST_SHARD_INDEX"])
paths = Path(f"splits/group-{index}.txt").read_text().splitlines()
if not paths:
    raise SystemExit("Empty assigned shard: use the nonempty shard count emitted by the plan job")
raise SystemExit(
    subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            *paths,
            "-p",
            "ci_esta.testing.pytest_completion",
            f"--completion-receipt=pytest-status-group-{index}",
            f"--junitxml=junit-group-{index}.xml",
            *sys.argv[1:],
        ],
        check=False,
    ).returncode
)
