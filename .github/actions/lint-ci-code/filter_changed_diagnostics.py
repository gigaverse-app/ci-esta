import argparse
import re
import subprocess
from pathlib import Path

DIAGNOSTIC = re.compile(r"^(?P<path>.+?):(?P<line>\d+):(?P<column>\d+):")
HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(?P<start>\d+)(?:,(?P<count>\d+))? @@")


def changed_lines(path: Path, base_sha: str, head_sha: str) -> set[int]:
    if not base_sha:
        return set(range(1, len(path.read_text().splitlines()) + 1))

    result = subprocess.run(
        ["git", "diff", "--unified=0", "--diff-filter=ACMR", base_sha, head_sha, "--", str(path)],
        check=True,
        capture_output=True,
        text=True,
    )
    lines: set[int] = set()
    for diff_line in result.stdout.splitlines():
        match = HUNK.match(diff_line)
        if not match:
            continue
        start = int(match.group("start"))
        count = int(match.group("count") or "1")
        lines.update(range(start, start + count))
    return lines


def workflow_block(path: Path, diagnostic_line: int) -> range:
    source = path.read_text().splitlines()
    index = diagnostic_line - 1
    if index >= len(source):
        return range(diagnostic_line, diagnostic_line + 1)

    indentation = len(source[index]) - len(source[index].lstrip())
    end = diagnostic_line
    for line_number, line in enumerate(source[index + 1 :], start=diagnostic_line + 1):
        if line.strip() and len(line) - len(line.lstrip()) <= indentation:
            break
        end = line_number
    return range(diagnostic_line, end + 1)


def should_keep(diagnostic: str, base_sha: str, head_sha: str, workflow_blocks: bool) -> bool:
    match = DIAGNOSTIC.match(diagnostic)
    if not match:
        return True

    path = Path(match.group("path"))
    line = int(match.group("line"))
    changed = changed_lines(path, base_sha, head_sha)
    relevant = workflow_block(path, line) if workflow_blocks else range(line, line + 1)
    return any(line_number in changed for line_number in relevant)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-sha", default="")
    parser.add_argument("--head-sha", required=True)
    parser.add_argument("--workflow-blocks", action="store_true")
    parser.add_argument("diagnostics", type=Path)
    args = parser.parse_args()

    retained = [
        diagnostic
        for diagnostic in args.diagnostics.read_text().splitlines()
        if should_keep(diagnostic, args.base_sha, args.head_sha, args.workflow_blocks)
    ]
    if retained:
        print("\n".join(retained))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
