"""Composite action entrypoint for JUnit scheduling hints."""

from __future__ import annotations

import glob
import os
from pathlib import Path

from ci_esta.testing.junit import learn_junit_timings, write_learned_timings
from ci_esta.testing.timing_artifacts import action_histories, artifact_name, github_client, history_branch
from ci_esta.testing.timing_store import learn_with_history


def main() -> None:
    reports = [Path(path) for path in sorted(glob.glob(os.environ["INPUT_JUNIT_PATTERN"], recursive=True))]
    output = Path(os.environ["INPUT_TIMING_OUTPUT"])
    if key := os.environ.get("INPUT_HISTORY_KEY"):
        client = github_client()
        try:
            run = client.get_run(int(os.environ["GITHUB_RUN_ID"]))
            history = Path(os.environ["RUNNER_TEMP"]) / f"{artifact_name(key)}-{run.id}-{run.run_attempt}.json"
            learned = learn_with_history(
                reports, history=history, key=key, output=output,
                complete_files=os.environ.get("INPUT_COMPLETE_FILES") == "true",
                # Keep reruns of an old checkout before newer source workflows,
                # including reporting-only reruns that download earlier reports.
                observed_at=run.created_at,
                snapshots=action_histories(client, key), run_id=run.id, attempt=run.run_attempt,
            )
            publish = (
                os.environ.get("INPUT_HISTORY_PUBLISH", "true") == "true"
                and run.event in {"push", "schedule", "workflow_dispatch"}
                and run.head_branch == history_branch()
                and os.environ.get("GITHUB_REF") == f"refs/heads/{history_branch()}"
            )
            with Path(os.environ["GITHUB_OUTPUT"]).open("a") as stream:
                stream.write(f"history-path={history}\nhistory-name={artifact_name(key)}\npublish={str(publish).lower()}\n")
        finally:
            client.close()
    else:
        learned = learn_junit_timings(reports)
        write_learned_timings(learned, output)
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
