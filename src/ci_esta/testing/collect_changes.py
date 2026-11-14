"""Adapt the collector's environment and files to the shared baseline policy."""

import os
from pathlib import Path

from pydantic import ValidationError

from ci_esta.testing.baseline_policy import FailureEvidence, collect_plan


def read_paths(path: str) -> tuple[str, ...] | None:
    file = Path(path)
    return tuple(file.read_text().splitlines()) if path and file.is_file() else None


def main() -> None:
    env = os.environ
    try:
        failures = FailureEvidence(
            sha=env.get("FAILED_SHA", ""),
            complete=env.get("FAILURES_COMPLETE") == "true",
            truncated=env.get("FAILURES_TRUNCATED") != "false",
            stale=env.get("FAILURES_STALE", "-1"),
            invalid=env.get("FAILURES_INVALID", "-1"),
            count=env.get("FAILURES_COUNT", "0"),
            paths=read_paths(env.get("FAILURES_FILE", "")) or (),
        )
    except ValidationError:
        # Unreadable evidence is not a reusable failure receipt.
        failures = FailureEvidence()
    result = collect_plan(
        Path.cwd(),
        event=env["EVENT_NAME"],
        head=env["CURRENT_SHA"],
        base=env.get("PR_BASE_SHA") or env.get("BEFORE_SHA") or "HEAD",
        pr_base=env.get("PR_BASE_SHA", ""),
        before=env.get("BEFORE_SHA", ""),
        validated=env.get("PR_INCREMENTAL_BASE_SHA", ""),
        failures=failures,
        complete_paths=read_paths("complete-pr-paths.txt"),
    )
    for name, item in (("changed-files.txt", result.primary), ("alternate-changed-files.txt", result.alternate)):
        path = Path(name)
        path.unlink(missing_ok=True)
        if item is not None and item.paths is not None:
            path.write_text("".join(value + "\n" for value in item.paths))
    Path("changed-files.tmp").unlink(missing_ok=True)
    print(f"::notice::{result.primary.reason}")
    if result.primary.paths is None:
        print("::warning::Complete change evidence unavailable; selector will run the full suite")
    with Path(env["GITHUB_OUTPUT"]).open("a") as output:
        output.write(
            f"base={result.primary.base}\nreused-failures={str(result.reused_failures).lower()}\n"
            f"alternate-base={result.alternate.base if result.alternate else ''}\n"
        )


if __name__ == "__main__":
    main()
