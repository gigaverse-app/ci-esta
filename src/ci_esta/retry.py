"""Print the commands that rerun what failed in a CI log: pytest tests, Bun test files and Lake modules."""

import argparse
import re
import shlex
import subprocess
import sys
from collections.abc import Iterable
from pathlib import Path

from ci_esta.lean import retry as lake

_LEAD = re.compile(lake._PREFIX)
# pytest's short test summary: `FAILED path.py::test[param] - message`, `ERROR path.py - message`.
_PYTEST = re.compile(r"(?:FAILED|ERROR) (\S+\.py(?:::\S.*)?)$")
# pytest's progress: `path.py ..F.x [ 29%]`, continued on lines without the path. It names the files with a
# failure even when `-r` leaves failures out of the summary, as `-rxX` does.
_PYTEST_PROGRESS = re.compile(r"(?:(\S+\.py) )?([.FEsxX]+)(?:\s+\[\s*\d+%\])?$")
# Bun prints each test file's path on a line of its own before that file's results.
_BUN_FILE = re.compile(r"(\S.*\.(?:test|spec)\.[cm]?[jt]sx?):$")
_BUN_FAILED = re.compile(r"\(fail\) |# Unhandled error between tests$")


def _plain(raw: str) -> str:
    """A log line without colour codes or the job, step and timestamp GitHub puts before it."""
    return _LEAD.sub("", lake._COLOR.sub("", raw.rstrip("\r\n")), count=1)


def _test_id(summary: str) -> str:
    """The test id in `id - message`. A parameter may itself hold ` - `, so cut where the brackets close."""
    cut = -1
    while (cut := summary.find(" - ", cut + 1)) >= 0:
        if summary.count("[", 0, cut) <= summary.count("]", 0, cut):
            return summary[:cut]
    return summary


def pytest_ids(repo: Path, lines: Iterable[str], skipped: list[str]) -> list[str]:
    """Failed and errored test ids in log order. `skipped` collects ids whose file is not in `repo`.

    A file whose progress shows a failure that no summary line names is returned whole, after the ids.
    """
    found: dict[str, None] = {}
    named: set[str] = set()
    unnamed: dict[str, None] = {}
    progressing = None
    for line in lines:
        progress = _PYTEST_PROGRESS.match(line)
        progressing = (progress[1] or progressing) if progress else None
        if progress and progressing and ("F" in progress[2] or "E" in progress[2]):
            unnamed[progressing] = None
        elif summary := _PYTEST.match(line):
            test = _test_id(summary[1])
            named.add(test.partition("::")[0])
            if (repo / test.partition("::")[0]).is_file():
                found[test] = None
            else:
                skipped.append(test)
    for file in unnamed:
        if file in named:
            continue
        if (repo / file).is_file():
            found[file] = None
        else:
            skipped.append(file)
    return list(found)


def bun_files(repo: Path, lines: Iterable[str], skipped: list[str]) -> list[str]:
    """Test files with a failed test or an error outside a test, in log order."""
    found: dict[str, None] = {}
    current = None
    for line in lines:
        if file := _BUN_FILE.match(line):
            current = file[1]
        elif current and _BUN_FAILED.match(line):
            if (repo / current).is_file():
                # Bun reads a bare argument as a filter on file names, and a path that starts with ./ as one file.
                found[current if current.startswith(("./", "/")) else f"./{current}"] = None
            else:
                skipped.append(current)
    return list(found)


def commands(repo: Path, raw: Iterable[str], skipped: list[str]) -> list[list[str]]:
    """One command per tool that reported a failure this checkout can rerun."""
    lines = [_plain(line) for line in raw]
    found = []
    if tests := pytest_ids(repo, lines, skipped):
        found.append(["pytest", *tests])
    if files := bun_files(repo, lines, skipped):
        found.append(["bun", "test", *files])
    if any(lake._FAILED.match(line) or lake._ERROR.match(line) or lake._SUMMARY.match(line) for line in lines):
        if modules := lake.targets(repo, None, lines, skipped):
            found.append(["lake", "build", *(f"+{module}" for module in modules)])
    return found


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ci-esta retry", description=__doc__)
    parser.add_argument("log", type=Path, help="A saved test, build or GitHub Actions job log, or - for stdin")
    parser.add_argument(
        "--repo", type=Path, default=Path.cwd(), help="The directory the failed command ran in (default: .)"
    )
    args = parser.parse_args(argv)
    skipped: list[str] = []
    try:
        if args.log == Path("-"):
            found = commands(args.repo, sys.stdin, skipped)
        else:
            with args.log.open(encoding="utf-8", errors="replace") as lines:
                found = commands(args.repo, lines, skipped)
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        print(f"ci-esta retry: {error}", file=sys.stderr)
        return 1
    if skipped:
        print(f"ci-esta retry: not in this checkout: {', '.join(dict.fromkeys(skipped))}", file=sys.stderr)
    for command in found:
        print(shlex.join(command))
    if not found:
        print("ci-esta retry: no pytest, Bun or Lake failure in the log names a file in this checkout", file=sys.stderr)
    return 0
