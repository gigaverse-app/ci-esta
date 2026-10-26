"""Bun evidence uses the portable Python report contract."""

import pytest

from ci_esta.testing.bun.models import BunExecution, ReportContext
from ci_esta.testing.bun.report import work_selection_report


@pytest.fixture
def execution():
    return BunExecution(mode="scoped", reason="Affected imports", fallback=False,
                        tested_sha="b" * 40, base="c" * 40, bun_version="1.4.2", total_files=657,
                        executed_files=["src/value.test.ts"], duration_ms=22000, exit_code=0)


def report(execution, **changes):
    return work_selection_report(execution.model_copy(update=changes),
                                 ReportContext(run_id=123, attempt=2, head_sha="a" * 40))


def test_preserves_source_and_tested_commits_and_measured_counts(execution):
    result = report(execution)
    assert result.head_sha == "a" * 40
    observed = result.decisions[0].execution
    assert observed.tested_sha == execution.tested_sha
    assert observed.status == "passed"
    assert observed.duration_seconds == 22
    assert observed.total_files == 657
    assert observed.executed_files == execution.executed_files


@pytest.mark.parametrize("changes,status", [
    ({"executed_files": None}, "incomplete"),
    ({"mode": "full"}, "incomplete"),
    ({"always_run_files": ["missing.test.ts"]}, "incomplete"),
    ({"exit_code": 1}, "failed"),
])
def test_missing_evidence_and_failures_cannot_report_passed(execution, changes, status):
    assert report(execution, **changes).decisions[0].execution.status == status


def test_reuse_describes_proof_without_claiming_fresh_execution(execution):
    result = report(execution, mode="reused", executed_files=[], receipt="proof", duration_ms=None)
    assert result.decisions[0].receipt == "proof"
    assert result.decisions[0].execution.status == "not_run"
    assert result.decisions[0].execution.duration_seconds is None


def test_capacity_is_separate_from_requested_concurrency(execution):
    observed = report(execution, cpu_count=16, workers=12, runner_label="16vcpu-runner").decisions[0].execution
    assert observed.cpu_count == 16
    assert observed.worker_limit == 12
    assert observed.runner_label == "16vcpu-runner"
    assert report(execution).decisions[0].execution.cpu_count is None
