#!/usr/bin/env python3
"""Publish a bounded Prometheus metric snapshot to Pushgateway."""

import base64
import json
import os
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path

_LABEL_NAME = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")
_RESERVED_GROUPING_LABELS = {
    "commit",
    "commit_sha",
    "job",
    "repository",
    "run_attempt",
    "run_id",
    "sha",
}
_FAILURE_MODES = {"fail", "warn"}


def _path_segment(value: str) -> str:
    return urllib.parse.quote(value, safe="")


def _grouping_pair(name: str, value: str) -> tuple[str, str]:
    if "/" not in value:
        return name, _path_segment(value)
    encoded_value = base64.urlsafe_b64encode(value.encode()).decode().rstrip("=")
    return f"{name}@base64", encoded_value


def parse_grouping_labels(raw_labels: str) -> dict[str, str]:
    parsed = json.loads(raw_labels)
    if not isinstance(parsed, dict):
        raise ValueError("grouping-labels must be a JSON object")

    labels: dict[str, str] = {}
    for raw_name, raw_value in parsed.items():
        if not isinstance(raw_name, str) or not _LABEL_NAME.fullmatch(raw_name):
            raise ValueError(f"{raw_name!r} is not a valid Prometheus label name")
        if raw_name in _RESERVED_GROUPING_LABELS:
            raise ValueError(
                f"{raw_name!r} is reserved; grouping keys must stay bounded and repository identity is automatic"
            )
        if not isinstance(raw_value, str) or not raw_value:
            raise ValueError(f"grouping label {raw_name!r} must have a non-empty string value")
        labels[raw_name] = raw_value
    return labels


def build_target(
    pushgateway_url: str,
    job: str,
    repository: str,
    grouping_labels: dict[str, str],
) -> str:
    if not pushgateway_url:
        raise ValueError("pushgateway-url is required")
    if not job:
        raise ValueError("job is required")
    if not repository:
        raise ValueError("GITHUB_REPOSITORY is required")

    job_name, job_value = _grouping_pair("job", job)
    repository_name, repository_value = _grouping_pair("repository", repository)
    segments = ["metrics", job_name, job_value, repository_name, repository_value]
    for name, value in sorted(grouping_labels.items()):
        if not _LABEL_NAME.fullmatch(name):
            raise ValueError(f"{name!r} is not a valid Prometheus label name")
        if name in _RESERVED_GROUPING_LABELS:
            raise ValueError(f"{name!r} is a reserved grouping label")
        grouping_name, grouping_value = _grouping_pair(name, value)
        segments.extend((grouping_name, grouping_value))
    return f"{pushgateway_url.rstrip('/')}/{'/'.join(segments)}"


def publish_snapshot(
    target: str,
    metrics_body: str,
    *,
    username: str,
    password: str,
    timeout_seconds: int,
) -> int:
    if bool(username) != bool(password):
        raise ValueError("username and password must either both be set or both be empty")

    headers = {"Content-Type": "text/plain; version=0.0.4"}
    if username:
        credentials = base64.b64encode(f"{username}:{password}".encode()).decode()
        headers["Authorization"] = f"Basic {credentials}"

    request = urllib.request.Request(
        target,
        data=metrics_body.encode(),
        method="PUT",
        headers=headers,
    )
    with urllib.request.urlopen(request, timeout=timeout_seconds) as response:  # noqa: S310
        return response.status


def _required_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise ValueError(f"{name} is required")
    return value


def main() -> int:
    failure_mode = os.environ.get("INPUT_FAILURE_MODE", "warn").strip()
    if failure_mode not in _FAILURE_MODES:
        print(
            "::error::INPUT_FAILURE_MODE must be either 'warn' or 'fail'",
            file=sys.stderr,
        )
        return 1

    try:
        metrics_file = Path(_required_env("INPUT_METRICS_FILE"))
        metrics_body = metrics_file.read_text()
        if not metrics_body.strip():
            raise ValueError(f"{metrics_file} is empty")

        target = build_target(
            _required_env("INPUT_PUSHGATEWAY_URL"),
            _required_env("INPUT_JOB"),
            _required_env("GITHUB_REPOSITORY"),
            parse_grouping_labels(os.environ.get("INPUT_GROUPING_LABELS", "{}")),
        )
        status = publish_snapshot(
            target,
            metrics_body,
            username=os.environ.get("INPUT_USERNAME", ""),
            password=os.environ.get("INPUT_PASSWORD", ""),
            timeout_seconds=int(os.environ.get("INPUT_TIMEOUT_SECONDS", "15")),
        )
    except Exception as exc:  # noqa: BLE001 - caller chooses telemetry failure policy
        annotation = "warning" if failure_mode == "warn" else "error"
        print(f"::{annotation}::Pushgateway publication failed: {exc}", file=sys.stderr)
        return 0 if failure_mode == "warn" else 1

    print(f"Published Prometheus snapshot to {target} ({status})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
