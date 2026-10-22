import pytest

from ci_esta.ci_observability.workflow_graph import dependencies


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
