"""Keep the tutorial executable against the installed public CLI."""

import subprocess
import sys
from pathlib import Path


def test_retention_tutorial():
    subprocess.run(
        [sys.executable, str(Path(__file__).resolve().parents[2] / "examples/timing-history/run.py")], check=True,
    )
