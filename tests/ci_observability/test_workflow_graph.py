from datetime import datetime, timezone

import pytest
import yaml

from ci_esta.ci_observability.critical_path import analyze
from ci_esta.ci_observability.models import GitHubJobV1
from ci_esta.ci_observability.workflow_graph import dependencies

# The second adoption trial (gigaverse-app/itsdangerous-ci-esta#1): every test job's name is an expression.
TRIAL = yaml.safe_load("""
jobs:
  plan: {}
  tests-linux:
    name: ${{ join(matrix.pool.versions, ', ') }}
    needs: plan
    strategy:
      matrix:
        pool: ${{ fromJSON(needs.plan.outputs.pools) }}
  tests:
    name: ${{ matrix.name || matrix.python }}
    strategy:
      matrix:
        include:
          - {name: Windows, python: '3.13', os: windows-latest}
          - {name: Mac, python: '3.13', os: macos-latest}
          - {name: PyPy, python: 'pypy-3.11', tox: pypy311}
  typing: {}
  validation-gate:
    name: Validation gate
    needs: [plan, tests-linux, tests, typing]
""")
# Run 42637251786 of that pull request: job name, then started and completed seconds after 14:42:00.
TRIAL_RUN = {"Mac": (13, 33), "PyPy": (12, 43), "typing": (12, 40), "Windows": (12, 45), "plan": (12, 21),
             "3.11, 3.10": (23, 44), "3.13, 3.12": (23, 34), "Validation gate": (47, 51)}


def test_nested_workflow_preserves_outer_barrier_and_inner_parallelism():
    workflow = {"jobs": {"plan": {}, "call": {"name": "Checks", "needs": "plan", "uses": "child"},
                         "gate": {"needs": "call"}}}
    child = {"jobs": {"a": {}, "b": {}, "finish": {"needs": ["a", "b"]}}}
    assert dependencies(workflow, resolve=lambda _, prefix: dependencies(child, prefix=prefix)) == {
        "plan": [], "Checks / a": ["plan"], "Checks / b": ["plan"],
        "Checks / finish": ["Checks / a", "Checks / b"],
        "gate": ["Checks / a", "Checks / b", "Checks / finish"],
    }


def test_skipped_call_is_a_zero_cost_barrier_without_fetching_its_source():
    workflow = {"jobs": {"plan": {}, "call": {"needs": "plan", "uses": "unavailable"},
                         "gate": {"needs": "call"}}}
    assert dependencies(workflow, skipped_calls={"call"}) == {
        "plan": [], "call": ["plan"], "gate": ["call"]}


def test_graph_comes_from_needs_including_matrix_names_and_aggregate_gates():
    workflow = {"jobs": {"plan": {}, "tests": {"needs": "plan", "strategy": {"matrix": {"os": ["linux"]}},
                "name": "Tests (${{ matrix.os }})"}, "gate": {"name": "Validation gate", "needs": ["plan", "tests"]}}}
    assert dependencies(workflow) == {"plan": [], "Tests (linux)": ["plan"],
                                      "Validation gate": ["plan", "Tests (linux)"]}


@pytest.mark.parametrize("jobs", [
    {"a": {"needs": "missing"}}, {"a": {"uses": "org/repo/.github/workflows/x.yml@main"}},
    {"a": {"name": "same"}, "b": {"name": "same"}}, {"a": {"needs": "${{ inputs.jobs }}"}},
])
def test_unsupported_or_ambiguous_topology_requires_an_explicit_complete_graph(jobs):
    with pytest.raises(ValueError):
        dependencies({"jobs": jobs})


def test_literal_matrix_names_are_evaluated_so_two_expression_names_stay_distinct():
    graph = dependencies(TRIAL)
    assert graph["Mac"] == graph["Windows"] == graph["PyPy"] == []
    assert graph["*"] == ["plan"]  # The pool names exist only at run time.
    assert graph["Validation gate"] == ["plan", "*", "Mac", "PyPy", "Windows", "typing"]


def test_trial_run_has_a_complete_critical_path():
    start = datetime(2026, 11, 9, 14, 42, tzinfo=timezone.utc)
    jobs = [GitHubJobV1(id=index, name=name, status="completed", conclusion="success",
                        started_at=start.replace(second=started), completed_at=start.replace(second=completed))
            for index, (name, (started, completed)) in enumerate(TRIAL_RUN.items())]
    result = analyze(start.replace(second=9), jobs, dependencies(TRIAL), ["Validation gate"])
    assert result.status == "complete", result.reason
    assert result.observed_path == ["Windows", "Validation gate"]
    assert {node.name for node in result.nodes} == set(TRIAL_RUN)


def test_main_layout_matrix_names_include_the_fallback_operand():
    workflow = {"jobs": {"tests": {"name": "${{ matrix.name || matrix.python }}", "strategy": {"matrix": {
        "include": [{"python": "3.13"}, {"name": "Mac", "python": "3.13"}, {"python": 3.10}]}}},
        "typing": {}}}
    assert set(dependencies(workflow)) == {"3.13", "Mac", "3.1", "typing"}


def test_axes_exclude_and_include_follow_github_expansion():
    matrix = {"os": ["ubuntu", "windows"], "python": ["3.12", "3.13"],
              "exclude": [{"os": "windows", "python": "3.12"}],
              "include": [{"os": "windows", "label": "win"}, {"os": "macos", "python": "3.13"}]}
    workflow = {"jobs": {"t": {"name": "${{ matrix.label || matrix.os }} ${{ matrix.python }}",
                               "strategy": {"matrix": matrix}}}}
    assert set(dependencies(workflow)) == {"ubuntu 3.12", "ubuntu 3.13", "win 3.13", "macos 3.13"}


@pytest.mark.parametrize("name", ["${{ format('py{0}', matrix.python) }}", "${{ matrix.versions }}"])
def test_other_expressions_and_non_scalar_values_stay_wildcards(name):
    workflow = {"jobs": {"t": {"name": name, "strategy": {"matrix": {"versions": [["3.12", "3.13"]],
                                                                       "python": ["3.12"]}}}}}
    assert dependencies(workflow) == {"*": []}


def test_a_skipped_matrix_job_keeps_its_wildcard():
    workflow = {"jobs": {"t": {"name": "${{ matrix.os }}", "strategy": {"matrix": {"os": ["linux"]}}}}}
    assert dependencies(workflow, skipped_calls={"${{ matrix.os }}"}) == {"*": []}


def test_two_run_time_expression_names_are_ambiguous_and_name_both_jobs():
    workflow = {"jobs": {"a": {"name": "${{ inputs.a }}"}, "b": {"name": "${{ inputs.b }}"}}}
    with pytest.raises(ValueError, match="jobs 'a' and 'b' both appear as"):
        dependencies(workflow)
