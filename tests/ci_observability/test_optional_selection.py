"""Reporting must work when the application and tool environment have no pytest."""
import subprocess
import sys
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from ci_esta.ci_observability.models import SelectionSectionV1
from ci_esta.ci_observability.report import build_unavailable_report
from ci_esta.ci_observability.work_selection import WorkDecisionV1, WorkSelectionV1, render_work_selection
from tests.ci_observability.test_selection import explanation


def test_core_reporting_without_pytest_selective():
    script = """
import importlib.abc
import sys
class NoPytest(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'pytest_selective', 'pytest'}:
            raise ModuleNotFoundError(fullname, name=fullname)
sys.meta_path.insert(0, NoPytest())
from datetime import datetime, timezone
from ci_esta.cli import main
from ci_esta.ci_observability.models import CiObservabilityReportV1
from ci_esta.ci_observability.work_selection import WorkSelectionV1, WorkDecisionV1
from ci_esta.ci_observability.report import build_unavailable_report, render_markdown, render_prometheus
report = build_unavailable_report(repository='example/typescript', run_id=123, run_attempt=1,
    head_sha='a'*40, pull_request_number=5, observed_at=datetime.now(timezone.utc), error='API unavailable')
restored = CiObservabilityReportV1.model_validate_json(report.model_dump_json())
plan = WorkSelectionV1(provider='bun', run_id=123, run_attempt=1, head_sha='a'*40,
    input_identity='tree abc', decisions=[WorkDecisionV1(name='Bun tests', decision='reused',
    reason='Identical inputs already passed', receipt='receipt abc')])
report = report.model_copy(update={'work_selection': plan})
restored = CiObservabilityReportV1.model_validate_json(report.model_dump_json())
assert 'Prior validation reused' in render_markdown(restored)
assert 'CI time and cost'  in render_markdown(restored)
assert render_prometheus(restored)
assert not any(name.startswith('pytest_selective') for name in sys.modules)
"""
    result = subprocess.run([sys.executable, '-c', script], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr




@pytest.mark.parametrize("decision", ["run", "unaffected", "reused"])
def test_provider_neutral_decisions_are_data_not_execution_claims(decision):
    item = WorkDecisionV1(name="Bun | <tests>", decision=decision, reason="Why | <script>",
                          receipt="proof" if decision == "reused" else None)
    plan = WorkSelectionV1(provider="bun", run_id=1, run_attempt=1, head_sha="a"*40,
                           input_identity="tree abc", decisions=[item])
    restored = WorkSelectionV1.model_validate_json(plan.model_dump_json())
    rendered = render_work_selection(restored)
    assert "<script>" not in rendered
    assert "Required gates and job results" in rendered
    assert "tests passed" not in rendered


@pytest.mark.parametrize("case", ["receipt", "fallback", "duplicates", "schema"])
def test_invalid_work_decisions_cannot_claim_reuse(case):
    payload = dict(provider="bun", run_id=1, run_attempt=1, head_sha="a"*40,
                   input_identity="tree abc", decisions=[dict(name="Tests", decision="run", reason="Default")])
    if case == "receipt":
        payload["decisions"][0]["decision"] = "reused"
    elif case == "fallback":
        payload["fallback"] = True
        payload["decisions"][0]["decision"] = "unaffected"
    elif case == "duplicates":
        payload["decisions"] *= 2
    else:
        payload["schema_version"] = "future/v9"
    with pytest.raises(ValidationError):
        WorkSelectionV1.model_validate(payload)


def test_saved_python_details_survive_without_provider(tmp_path):
    report = build_unavailable_report(repository="example/python", run_id=123, run_attempt=1,
        head_sha="a"*40, pull_request_number=5, observed_at=datetime.now(timezone.utc), error="API unavailable")
    report = report.model_copy(update={"test_selection": SelectionSectionV1(explanation=explanation())})
    path = tmp_path / "python-report.json"
    path.write_text(report.model_dump_json(), encoding="utf-8")
    script = """
import importlib.abc, json, sys
class NoSelector(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] == 'pytest_selective':
            raise ModuleNotFoundError(fullname, name=fullname)
sys.meta_path.insert(0, NoSelector())
from pathlib import Path
from ci_esta.ci_observability.models import CiObservabilityReportV1
from ci_esta.ci_observability.report import render_markdown
original = json.loads(Path(sys.argv[1]).read_text())
restored = CiObservabilityReportV1.model_validate(original)
assert restored.model_dump(mode='json')['test_selection'] == original['test_selection']
assert 'ci-esta[selection]' in render_markdown(restored)
"""
    result = subprocess.run([sys.executable, "-c", script, str(path)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_large_work_inventory_keeps_sticky_bounded_and_preserves_json():
    plan = WorkSelectionV1(provider="bun", run_id=1, run_attempt=1, head_sha="a"*40,
        input_identity="tree abc", decisions=[WorkDecisionV1(name=f"Tests {index}", decision="run",
        reason="x" * 1000) for index in range(100)])
    assert len(render_work_selection(plan)) < 12000
    assert "80 additional work decisions" in render_work_selection(plan)
    assert len(WorkSelectionV1.model_validate_json(plan.model_dump_json()).decisions) == 100


def test_bun_execution_reports_counts_without_inventing_time_savings():
    plan = WorkSelectionV1(provider="bun", run_id=1, run_attempt=1, head_sha="a"*40,
        input_identity="b"*40, decisions=[dict(name="Bun tests", decision="run", reason="Native affected tests",
        execution=dict(mode="scoped", status="passed", total_files=657, executed_files=["src/value.test.ts"],
                       duration_seconds=22, tested_sha="b"*40, runtime="Bun 1.4.2"))])
    rendered = render_work_selection(plan)
    assert "1 / 657" in rendered
    assert "656 test files avoided" in rendered
    assert "not a measured time saving" in rendered
    assert "src/value.test.ts" in rendered
    assert "22s" in rendered


@pytest.mark.parametrize("changes", [dict(executed_files=None), dict(executed_files=["x", "x"]),
                                    dict(total_files=0), dict(mode="reused")])
def test_invalid_execution_inventory_cannot_claim_success(changes):
    from ci_esta.ci_observability.work_selection import WorkExecutionV1

    with pytest.raises(ValidationError):
        WorkExecutionV1.model_validate(dict(mode="scoped", status="passed", total_files=1,
            executed_files=["x"], tested_sha="a"*40, runtime="Bun 1.4.2") | changes)
