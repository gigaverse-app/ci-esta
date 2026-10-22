"""
Shared CI shell entry points; env contracts are documented in each script.

For tests and local runs only. A workflow must not call `python -m
ci_esta.testing.evidence` from a pull request job: that imports the PR
head's locked backend-common, which may predate this module. Workflows use the
`collect-pytest-changes` and `verify-pytest-completion` actions, which run these
same scripts from the ref the workflow pins.
"""

from __future__ import annotations

import argparse
import subprocess
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=["collect", "verify"])
    args = parser.parse_args()
    script = Path(__file__).with_name("evidence_scripts") / f"{args.operation}.sh"
    return subprocess.run(["bash", str(script)], check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())
