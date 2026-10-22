from datetime import datetime, timedelta, timezone

import pytest

from ci_esta.ci_observability.critical_path import analyze
from ci_esta.ci_observability.models import GitHubJobV1

START = datetime(2026, 1, 1, tzinfo=timezone.utc)


def job(name, start, end, conclusion="success", attempt=1):
    return GitHubJobV1(id=sum(map(ord, name)), name=name, run_attempt=attempt,
                       status="completed", conclusion=conclusion,
                       started_at=START + timedelta(seconds=start),
                       completed_at=START + timedelta(seconds=end))


def test_observed_path_separates_dependency_wait_from_execution_and_cpm_slack():
    jobs = [job("plan", 2, 5), job("fast", 6, 10), job("slow", 8, 20), job("gate", 22, 23)]
    graph = {"plan": [], "fast": ["plan"], "slow": ["plan"], "gate": ["fast", "slow"]}
    result = analyze(START, jobs, graph, ["gate"])
    assert result.status == "complete"
    assert result.observed_path == ["plan", "slow", "gate"]
    assert result.elapsed_seconds == 23
    assert result.execution_path == ["plan", "slow", "gate"]
    assert result.execution_seconds == 16
    assert sum(n.delay_seconds for n in result.nodes if n.name in result.observed_path) == 7
    assert {n.name: n.slack_seconds for n in result.nodes}["fast"] == 8


def test_longest_job_is_not_necessarily_on_the_gate_path():
    result = analyze(START, [job("test", 1, 5), job("gate", 6, 7), job("report", 8, 100)],
                     {"test": [], "gate": ["test"], "report": []}, ["gate"])
    assert result.elapsed_seconds == 7
    assert result.observed_path == ["test", "gate"]
    assert "report" not in [n.name for n in result.nodes]


def test_queue_delay_can_make_observed_path_differ_from_execution_path():
    result = analyze(START, [job("cpu", 0, 20), job("delayed", 30, 31), job("gate", 32, 33)],
                     {"cpu": [], "delayed": [], "gate": ["cpu", "delayed"]}, ["gate"])
    assert result.observed_path == ["delayed", "gate"]
    assert result.execution_path == ["cpu", "gate"]
    assert result.execution_seconds == 21
    assert result.elapsed_seconds == 33


def test_matrix_expansion_and_skipped_nodes_preserve_dependency_edges():
    result = analyze(START, [job("plan", 0, 5), job("tests (a)", 6, 9),
                     job("tests (b)", 0, 0, "skipped"), job("gate", 10, 11)],
                     {"plan": [], "tests (*)": ["plan"], "gate": ["tests (*)"]}, ["gate"])
    assert result.status == "complete"
    assert result.observed_path == ["plan", "tests (a)", "gate"]
    assert next(n for n in result.nodes if n.name == "tests (b)").execution_seconds == 0


@pytest.mark.parametrize("graph,jobs,gates", [
    ({"a": ["b"], "b": ["a"]}, [job("a", 0, 1), job("b", 2, 3)], ["b"]),
    ({"a": ["missing"]}, [job("a", 0, 1)], ["a"]),
    ({"a": []}, [job("a", 0, 1), job("a", 0, 1)], ["a"]),
    ({"a": [], "b": ["a"]}, [job("a", 0, 5), job("b", 1, 2)], ["b"]),
    ({"a": []}, [job("a", 0, 1)], ["missing"]),
    ({"*": [], "a": []}, [job("a", 0, 1)], ["a"]),
    ({"a": []}, [job("a", 0, 1), job("b", 0, 2, attempt=2)], ["a"]),
])
def test_uncertain_graph_or_identity_is_unavailable_not_a_fabricated_path(graph, jobs, gates):
    result = analyze(START, jobs, graph, gates)
    assert result.status == "unavailable"
    assert result.reason
    assert result.elapsed_seconds is None


def test_missing_running_timestamps_do_not_turn_into_zero_duration():
    pending = GitHubJobV1(id=1, name="a", status="queued")
    assert analyze(START, [pending], {"a": []}, ["a"]).status == "unavailable"


def test_failed_job_can_explain_time_to_failed_validation_without_claiming_success():
    result = analyze(START, [job("test", 0, 10, "failure"), job("gate", 11, 12, "failure")],
                     {"test": [], "gate": ["test"]}, ["gate"])
    assert result.status == "complete"
    assert result.elapsed_seconds == 12
    assert result.nodes[-1].conclusion == "failure"
