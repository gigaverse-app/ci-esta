"""Composite action entrypoint for JUnit scheduling hints."""

from __future__ import annotations

import glob
import os
from pathlib import Path

from ci_esta.testing.junit import learn_junit_timings, write_learned_timings


def main() -> None:
    reports = [Path(path) for path in sorted(glob.glob(os.environ["INPUT_JUNIT_PATTERN"], recursive=True))]
    learned = learn_junit_timings(reports)
    write_learned_timings(learned, Path(os.environ["INPUT_TIMING_OUTPUT"]))
    summary = (
        f"Learned {len(learned.durations)} test-file costs from {len(reports)} reports; "
        f"{learned.unmapped_cases} unmapped and {learned.skipped_cases} skipped cases. "
        "These are scheduling hints, not completion or reuse evidence.\n"
    )
    print(summary)
    if destination := os.environ.get("GITHUB_STEP_SUMMARY"):
        with Path(destination).open("a", encoding="utf-8") as stream:
            stream.write(summary)


if __name__ == "__main__":
    main()
