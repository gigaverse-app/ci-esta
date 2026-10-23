from datetime import datetime, timezone

import pytest

from ci_esta.ci_observability.report import build_unavailable_report, render_markdown
from ci_esta.ci_observability.work_selection import WorkDecisionV1, WorkExecutionV1, WorkSelectionV1


def report_with_work(*decisions):
    report = build_unavailable_report(repository="example/bun", run_id=123, run_attempt=1,
        head_sha="a" * 40, pull_request_number=5, observed_at=datetime.now(timezone.utc), error="API unavailable")
    plan = WorkSelectionV1(provider="Bun", run_id=123, run_attempt=1, head_sha="a" * 40,
                          input_identity="tree abc", decisions=list(decisions))
    return report.model_copy(update={"work_selection": plan})


def work(name="Bun tests", *, files=None, status="incomplete", mode="scoped"):
    return WorkDecisionV1(name=name, decision="run", reason="Affected source",
        execution=WorkExecutionV1(mode=mode, status=status, total_files=10,
                                 executed_files=files, tested_sha="a" * 40, runtime="Bun 1.4.2"))


@pytest.mark.parametrize("status", ["passed", "failed", "incomplete"])
def test_bun_headline_uses_observed_inventory_without_claiming_selection_or_success(status):
    rendered = render_markdown(report_with_work(work(files=["a.test.ts", "b.test.ts"], status=status)))
    header = rendered.split("\n---\n", 1)[0]
    assert "![executed: 2 / 10 files]" in header
    assert "![selected:" not in header
    assert "2 / 10 files executed" in rendered.split("</summary>", 1)[0]
    assert "Required checks passed" not in header


def test_unknown_execution_keeps_requested_work_visible_without_inventing_file_counts():
    rendered = render_markdown(report_with_work(work()))
    header = rendered.split("\n---\n", 1)[0]
    assert "![requested: 1 / 1 work units]" in header
    assert "![executed:" not in header


def test_multiple_work_inventories_are_not_summed_or_misrepresented_as_test_files():
    rendered = render_markdown(report_with_work(work("first", files=["shared.test.ts"]),
                                               work("second", files=["shared.test.ts"])))
    header = rendered.split("\n---\n", 1)[0]
    assert "![requested: 2 / 2 work units]" in header
    assert "![executed:" not in header


def test_reuse_plan_does_not_claim_new_execution():
    item = WorkDecisionV1(name="Bun tests", decision="reused", reason="Matching receipt", receipt="proof")
    header = render_markdown(report_with_work(item)).split("\n---\n", 1)[0]
    assert "![requested: 0 / 1 work units]" in header
    assert "![executed:" not in header
