"""Record composite-action facts without requiring an installed CI-esta package."""

from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path


def record(kind: str) -> None:
    event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text())
    scope = os.environ["MEASUREMENT_SCOPE"]
    attempt = int(os.environ["GITHUB_RUN_ATTEMPT"])
    data = {
        "schema_version": f"ci-esta/{kind}/v1",
        "run_id": int(os.environ["GITHUB_RUN_ID"]), "run_attempt": attempt,
        "head_sha": event.get("pull_request", {}).get("head", {}).get("sha", os.environ["GITHUB_SHA"]),
        "job": os.environ["GITHUB_JOB"], "scope": scope,
    }
    if kind == "cache":
        outcome = "miss"
        if os.environ["CACHE_ENABLED"] != "true":
            outcome = "disabled"
        elif os.environ["CACHE_RESTORE_OUTCOME"] == "failure":
            outcome = "unavailable"
        elif os.environ["CACHE_HIT"] == "true":
            outcome = "hit" if os.environ["CACHE_USABLE"] == "true" else "repaired"
        data.update(outcome=outcome, sync_seconds=float(os.environ["CACHE_SYNC_SECONDS"]))
    elif kind == "image":
        data.update(digest=os.environ["IMAGE_DIGEST"])
    else:
        raise ValueError(f"unsupported measurement kind: {kind}")
    suffix = hashlib.sha256(scope.encode()).hexdigest()[:16]
    name = f"ci-esta-{kind}-{os.environ['GITHUB_JOB']}-{suffix}-{attempt}"
    path = Path(os.environ["RUNNER_TEMP"]) / f"{name}.json"
    path.write_text(json.dumps(data) + "\n")
    with Path(os.environ["GITHUB_OUTPUT"]).open("a") as output:
        output.write(f"measurement-path={path}\nmeasurement-name={name}\n")


if __name__ == "__main__":
    try:
        record(sys.argv[1])
    except Exception as error:
        print(f"::warning::Execution measurement unavailable: {error}")
