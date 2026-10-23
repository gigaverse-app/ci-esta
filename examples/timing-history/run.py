"""Run from any directory with: uv run python examples/timing-history/run.py.

Uses real pytest reports and the installed CLI in a disposable Git repository.
"""

import json
import shutil
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory


def run(root: Path, *args: str) -> None:
    subprocess.run(list(args), cwd=root, check=True)


def main() -> None:
    with TemporaryDirectory(prefix="ci-esta-history-") as directory:
        root = Path(directory)
        shutil.copytree(Path(__file__).parent / "tests", root / "tests")
        run(root, "git", "init", "-q")
        run(root, "git", "add", "tests")
        cli = (sys.executable, "-m", "ci_esta.testing.cli")
        for name in ("alpha", "beta"):
            run(root, sys.executable, "-m", "pytest", "-q", f"tests/test_{name}.py", f"--junitxml={name}.xml")
        common = ("--history", "history.json", "--complete-files")
        run(root, *cli, "learn", "alpha.xml", *common, "--observed-at", "2026-10-23T00:00:00Z")
        run(root, *cli, "learn", "beta.xml", *common, "--observed-at", "2026-10-24T00:00:00Z")
        before = json.loads((root / ".test_durations").read_text())
        assert set(before) == {"tests/test_alpha.py", "tests/test_beta.py"}
        run(root, *cli, "learn", "alpha.xml", *common, "--observed-at", "2026-10-20T00:00:00Z")
        assert json.loads((root / ".test_durations").read_text()) == before
        run(root, *cli, "plan", "--shards", "2", "--exact-files", "--output-dir", "splits")
        paths = [line for path in (root / "splits").glob("*.txt") for line in path.read_text().splitlines()]
        assert sorted(paths) == sorted(before)
        print("PASS: partial runs retain both files; stale reports preserve costs; every file remains planned")


if __name__ == "__main__":
    main()
