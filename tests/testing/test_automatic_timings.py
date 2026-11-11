"""Automatic learning must retain the same merged/final-attempt boundary."""
import json
import os
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import httpx
import pytest

from ci_esta.ci_observability.github import GitHubActionsClient
from ci_esta.measurements import MeasurementIdentity
from ci_esta.testing import automatic_timings, timing_artifacts, timing_feedback
from ci_esta.testing.junit import junit_report_identity
from tests.testing.merged_pr_server import MergedPRServer


@pytest.mark.parametrize("xdist", [False, True])
def test_pytest_stamps_the_execution_identity_into_its_actual_junit(tmp_path, xdist):
    (tmp_path / "test_example.py").write_text("def test_example(): pass\n")
    event = tmp_path / "event.json"
    event.write_text(json.dumps({"pull_request": {"head": {"sha": "b" * 40}}}))
    env = {**os.environ, "PYTHONPATH": str(Path("src").resolve()), "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
           "PYTEST_XDIST_WORKER": "inherited-parent",
           "GITHUB_ACTIONS": "true", "GITHUB_RUN_ID": "12", "GITHUB_RUN_ATTEMPT": "2",
           "GITHUB_SHA": "a" * 40, "GITHUB_EVENT_PATH": str(event)}
    result = subprocess.run([sys.executable, "-m", "pytest", "-p", "ci_esta.testing.pytest_provenance",
                             *(["-p", "xdist.plugin", "-n", "2"] if xdist else []),
                             "--junitxml=junit.xml", "-q"], cwd=tmp_path, env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    identity = junit_report_identity(tmp_path / "junit.xml")
    assert identity == MeasurementIdentity(run_id=12, run_attempt=2, head_sha="b" * 40)


@pytest.mark.parametrize("xml", ["<testsuite/>", "<testsuite><properties><property name='ci-esta.execution' value='{}'/></properties></testsuite>"])
def test_unattested_reports_are_not_assumed_fresh(tmp_path, xml):
    path = tmp_path / "junit.xml"
    path.write_text(xml)
    assert junit_report_identity(path) is None




def automatic_source(server):
    server.ready()
    server.payloads[1]["origin"] = {"run_id": 1, "run_attempt": 1, "head_sha": server.runs[1]["head_sha"]}
    server.payloads[1]["pull_request"] = 7
    server.artifacts[1]["name"] = automatic_timings.automatic_name("unit", "file-costs")
    # Automatic admission must not require manually adding a PR marker.
    server.jobs[1][0]["steps"] = []
    return server.artifacts[1]


def test_automatic_restore_admits_only_final_merged_observations():
    server = MergedPRServer()
    automatic_source(server)
    decision = automatic_timings.stage_automatic(server.client, "unit", "main", 7, 1)
    assert decision.promotion is not None
    assert decision.promotion.measurements[0].durations == {"test_a.py": 1}
    server.close()


@pytest.mark.parametrize("change", ["open", "newer_pending", "newer_failed", "wrong_attempt", "missing_origin", "late_job", "fork", "wrong_pr", "wrong_head", "wrong_run"])
def test_automatic_restore_never_relaxes_source_admission(change):
    server = MergedPRServer()
    automatic_source(server)
    if change == "open":
        server.pr["merged_at"] = None
    elif change in {"newer_pending", "newer_failed"}:
        server.pr["merged_at"] = None
        server.start()
        if change == "newer_failed":
            server.finish(2, "failure")
        server.merge()
    elif change == "wrong_attempt":
        server.payloads[1]["origin"]["run_attempt"] = 2
    elif change == "wrong_pr":
        server.payloads[1]["pull_request"] = 8
    elif change == "wrong_head":
        server.payloads[1]["origin"]["head_sha"] = "f" * 40
    elif change == "wrong_run":
        server.payloads[1]["origin"]["run_id"] = 99
    elif change == "missing_origin":
        del server.payloads[1]["origin"]
    elif change == "late_job":
        server.jobs[1][0]["completed_at"] = server.time()
    else:
        server.pr["head"]["repo"]["full_name"] = "fork/repo"
    assert automatic_timings.stage_automatic(server.client, "unit", "main", 7, 1).promotion is None
    server.close()




def test_existing_learn_and_restore_actions_need_no_new_inputs(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    subprocess.run(["git", "init", "-q"], check=True)
    Path("test_a.py").write_text("def test_ok(): pass\n")
    subprocess.run(["git", "add", "test_a.py"], check=True)
    server = MergedPRServer()
    server.start()
    Path("event.json").write_text('{"pull_request":{"number":7}}')
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(tmp_path / "event.json"))
    origin = MeasurementIdentity(run_id=1, run_attempt=1, head_sha="1" * 40)
    suite = ET.Element("testsuite")
    properties = ET.SubElement(suite, "properties")
    ET.SubElement(properties, "property", name="ci-esta.execution", value=origin.model_dump_json())
    ET.SubElement(suite, "testcase", file="test_a.py", time="12")
    ET.ElementTree(suite).write("junit.xml")
    for key, value in {
        "INPUT_JUNIT_PATTERN": "junit.xml", "INPUT_TIMING_OUTPUT": "costs.json",
        "INPUT_HISTORY_KEY": "unit", "INPUT_COMPLETE_FILES": "true", "INPUT_HISTORY_BRANCH": "main",
        "INPUT_TIMING_ARTIFACT_NAME": "file-costs", "GITHUB_RUN_ID": "1", "GITHUB_RUN_ATTEMPT": "1",
        "GITHUB_REF": "refs/pull/7/merge", "GITHUB_OUTPUT": "outputs", "RUNNER_TEMP": str(tmp_path),
    }.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(timing_feedback, "github_client", lambda: server.client)
    timing_feedback.main()
    outputs = dict(line.split("=", 1) for line in Path("outputs").read_text().splitlines())
    assert "automatic-path" in outputs
    assert "measurement-path" not in outputs  # No explicit fresh-reports declaration.
    measured = json.loads(Path(outputs["automatic-path"]).read_text())
    assert measured["durations"] == {"test_a.py": 12}
    server.upload(1)
    server.payloads[1] = measured
    server.artifacts[1]["name"] = outputs["automatic-name"]
    server.pass_gate(1)
    server.finish(1, "success")
    # Recreate the real HTTP client after each action closes its own client.
    monkeypatch.setattr(timing_artifacts, "github_client", lambda: GitHubActionsClient(
        "org/repo", "fake", transport=httpx.MockTransport(server.handle)))
    Path("costs.json").write_text('{"test_a.py::seed":99,"test_b.py":30}')
    timing_artifacts.restore()
    assert json.loads(Path("costs.json").read_text()) == {"test_a.py::seed": 99, "test_b.py": 30}
    server.merge()
    timing_artifacts.restore()
    assert json.loads(Path("costs.json").read_text()) == {"test_a.py": 12, "test_b.py": 30}


@pytest.mark.parametrize("stamped", [False, True])
def test_reporter_rerun_cannot_relabel_retained_xml(tmp_path, monkeypatch, stamped):
    # Same workflow and SHA, but an earlier attempt, must not become fresh data.
    monkeypatch.chdir(tmp_path)
    subprocess.run(["git", "init", "-q"], check=True)
    Path("test_a.py").write_text("def test_ok(): pass\n")
    subprocess.run(["git", "add", "test_a.py"], check=True)
    Path("junit.xml").write_text('<testsuite><testcase file="test_a.py" time="12"/></testsuite>')
    server = MergedPRServer()
    server.start()
    server.rerun(1)
    Path("event.json").write_text('{"pull_request":{"number":7}}')
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(tmp_path / "event.json"))
    if stamped:
        suite = ET.parse("junit.xml").getroot()
        properties = ET.SubElement(suite, "properties")
        origin = MeasurementIdentity(run_id=1, run_attempt=1, head_sha="1" * 40)
        ET.SubElement(properties, "property", name="ci-esta.execution", value=origin.model_dump_json())
        ET.ElementTree(suite).write("junit.xml")
    for key, value in {
        "INPUT_JUNIT_PATTERN": "junit.xml", "INPUT_TIMING_OUTPUT": "costs.json",
        "INPUT_HISTORY_KEY": "unit", "INPUT_COMPLETE_FILES": "true", "INPUT_HISTORY_BRANCH": "main",
        "INPUT_TIMING_ARTIFACT_NAME": "file-costs", "GITHUB_RUN_ID": "1", "GITHUB_RUN_ATTEMPT": "2",
        "GITHUB_REF": "refs/pull/7/merge", "GITHUB_OUTPUT": "outputs", "RUNNER_TEMP": str(tmp_path),
    }.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(timing_feedback, "github_client", lambda: server.client)
    timing_feedback.main()
    assert "automatic-path" not in Path("outputs").read_text()
