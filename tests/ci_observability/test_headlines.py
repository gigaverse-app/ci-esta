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
    assert "![selected: unavailable]" in header
    assert "2 / 10 files</strong> <sub>executed</sub>" in rendered.split("</summary>", 1)[0]
    assert "Required checks passed" not in header


def test_unknown_execution_does_not_invent_file_counts():
    rendered = render_markdown(report_with_work(work()))
    header = rendered.split("\n---\n", 1)[0]
    assert "![selected: unavailable]" in header
    assert "![executed: unavailable]" in header


def test_multiple_work_inventories_are_not_summed_or_misrepresented_as_test_files():
    rendered = render_markdown(report_with_work(work("first", files=["shared.test.ts"]),
                                               work("second", files=["shared.test.ts"])))
    header = rendered.split("\n---\n", 1)[0]
    assert "![selected: unavailable]" in header
    assert "![executed: unavailable]" in header


def test_reuse_plan_does_not_claim_new_execution():
    item = WorkDecisionV1(name="Bun tests", decision="reused", reason="Matching receipt", receipt="proof")
    header = render_markdown(report_with_work(item)).split("\n---\n", 1)[0]
    assert "![selected: unavailable]" in header
    assert "![executed: unavailable]" in header
    assert "![reused: 1 / 1 work units]" in header
    sticky = render_markdown(report_with_work(item))
    assert "reuse unmeasured" not in sticky
    assert "1 / 1 work units reused" in sticky.split("What else avoided work?")[1]
    assert "receipt `proof`" in sticky


def test_full_selection_is_not_replaced_by_partial_execution_on_failure():
    rendered = render_markdown(report_with_work(work(mode="full", status="failed", files=["a.test.ts"])))
    header = rendered.split("\n---\n", 1)[0]
    assert "![selected: 10 / 10 files]" in header
    assert "![executed: 1 / 10 files]" in header
    assert "![reused: 0 / 1 work units]" in header


def test_python_and_bun_have_the_same_headline_fields_and_section_order():
    import re

    from ci_esta.ci_observability.models import SelectionSectionV1
    from tests.ci_observability.test_selection import explanation

    bun = report_with_work(work(files=["a.test.ts"]))
    python = bun.model_copy(update={"work_selection": None, "test_selection": SelectionSectionV1(
        explanation=explanation())})
    outputs = [render_markdown(report) for report in (python, bun)]
    for output in outputs:
        header = output.split("\n---\n", 1)[0]
        fields = re.findall(r"!\[([^:\]]+):", header)
        assert fields == ["selected", "executed", "reused", "runner", "est. cost"]
        assert "![est. cost: unavailable]" in header
        assert "<summary><strong>Selection and execution</strong>" in output
    assert "![executed: unavailable]" in outputs[0]
    assert "![reused: unavailable]" in outputs[0]


@pytest.mark.parametrize("mode,decision,selected", [("none", "unaffected", "0 / 10 files"),
                                                   ("reused", "reused", "unavailable")])
def test_no_execution_and_reuse_are_distinct(mode, decision, selected):
    item = WorkDecisionV1(name="Bun tests", decision=decision, reason="Evidence", receipt="proof" if mode == "reused" else None,
        execution=WorkExecutionV1(mode=mode, status="not_run", total_files=10, executed_files=[],
                                 tested_sha="a" * 40, runtime="Bun 1.4.2"))
    header = render_markdown(report_with_work(item)).split("\n---\n", 1)[0]
    assert f"![selected: {selected}]" in header
    assert "![executed: 0 / 10 files]" in header
    assert f"![reused: {int(mode == 'reused')} / 1 work units]" in header


def test_unaffected_bun_inputs_still_select_always_run_contracts():
    item = work(mode="none", status="passed", files=["contract.test.ts"])
    item = item.model_copy(update={"execution": item.execution.model_copy(
        update={"always_run_files": ["contract.test.ts"]})})
    header = render_markdown(report_with_work(item)).split("\n---\n", 1)[0]
    assert "![selected: 1 / 10 files]" in header
    assert "![executed: 1 / 10 files]" in header
