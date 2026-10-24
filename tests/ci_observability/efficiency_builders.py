"""Exact-attempt execution evidence shared by sticky coverage and pool tests."""

from datetime import datetime, timedelta, timezone

from ci_esta.ci_observability.models import GitHubJobV1, GitHubRunV1
from ci_esta.ci_observability.report import build_report
from ci_esta.measurements import ShardPoolMeasurement


def pool(**changes):
    return ShardPoolMeasurement.model_validate(dict(
        run_id=431, run_attempt=2, head_sha="a" * 40, pool="tests:1-2", configured_shards=2, cpu_count=16,
        shards=[dict(index=1, start_seconds=0, end_seconds=10, exit_code=0),
                dict(index=2, start_seconds=0, end_seconds=5, exit_code=0)], **changes))


def report(**job_fields):
    now = datetime(2026, 10, 23, tzinfo=timezone.utc)
    run = GitHubRunV1(id=431, run_attempt=2, head_sha="a" * 40, name="CI", status="completed",
                     created_at=now, run_started_at=now)
    job = GitHubJobV1(id=11, name="Tests", run_attempt=2, status="completed", conclusion="success",
                     started_at=now, completed_at=now + timedelta(seconds=60), **job_fields)
    return build_report(repository="org/repo", pull_request_number=1, run=run,
                        latest_jobs=[job], billing_jobs=[job], commit_statuses=[], gate_selectors=[],
                        observed_at=now + timedelta(seconds=60))
