import pytest

from ci_esta.ci_observability.workflow_graph import dependencies


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
    assert dependencies(workflow) == {"plan": [], "Tests (*)": ["plan"],
                                      "Validation gate": ["plan", "Tests (*)"]}


@pytest.mark.parametrize("jobs", [
    {"a": {"needs": "missing"}}, {"a": {"uses": "org/repo/.github/workflows/x.yml@main"}},
    {"a": {"name": "same"}, "b": {"name": "same"}}, {"a": {"needs": "${{ inputs.jobs }}"}},
])
def test_unsupported_or_ambiguous_topology_requires_an_explicit_complete_graph(jobs):
    with pytest.raises(ValueError):
        dependencies({"jobs": jobs})
