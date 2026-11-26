"""Non-Python workflow inputs use the same declaration graph as selective tests."""

import subprocess

import pytest
from selective_deps import DependencyDeclarationError

from ci_esta.workflow_graph import WorkflowGraph, changed_job_lanes
from tests.testing.git_repo import commit, write

WORKFLOW = ".github/workflows/proof.yml"
MANIFEST = "scripts/.gv-dependencies.yaml"


@pytest.fixture
def repo(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    write(
        tmp_path,
        WORKFLOW,
        """
jobs:
  proof:
    if: fromJSON(needs.plan.outputs.lanes).proof
    steps:
      - run: lake env lean scripts/Check.lean
  other:
    if: fromJSON(needs.plan.outputs.lanes).other
    steps:
      - run: lake env lean scripts/Other.lean
""",
    )
    write(tmp_path, "scripts/Check.lean", "example : True := trivial\n")
    write(tmp_path, "scripts/Other.lean", "example : True := trivial\n")
    write(tmp_path, "scripts/Helper.lean")
    write(tmp_path, "scripts/data.txt", "# gv:test-dependency: scripts/unrelated.txt\n")
    write(tmp_path, "scripts/unrelated.txt")
    write(
        tmp_path,
        MANIFEST,
        """
dependencies:
  - readers: [Check.lean]
    inputs: [Helper.lean]
  - readers: [Helper.lean]
    inputs: [Check.lean]
  - readers: [Helper.lean]
    inputs: [data.txt]
    kind: content
""",
    )
    return tmp_path


def test_lean_lane_follows_declared_imports_but_stops_at_content(repo):
    base = commit(repo)
    before = WorkflowGraph(repo, base)
    for path in ("scripts/Helper.lean", "scripts/data.txt", MANIFEST):
        assert changed_job_lanes(before, before, {path}) == {
            f"workflow input: {path} (run by {WORKFLOW}#proof)": {"proof"}
        }
    assert changed_job_lanes(before, before, {"scripts/unrelated.txt"}) == {}
    assert before.jobs[WORKFLOW, "proof"].content_inputs == {"scripts/data.txt"}


def test_removed_sidecar_remains_an_input_of_the_old_job(repo):
    sidecar = "scripts/Other.lean.gv-dependency.yaml"
    write(repo, sidecar, "dependencies:\n  - inputs: [unrelated.txt]\n")
    base = commit(repo)
    (repo / sidecar).unlink()
    head = commit(repo)
    assert changed_job_lanes(WorkflowGraph(repo, base), WorkflowGraph(repo, head), {sidecar}) == {
        f"workflow input: {sidecar} (run by {WORKFLOW}#other)": {"other"}
    }


def test_invalid_lean_declaration_reports_its_path(repo):
    write(repo, MANIFEST, "dependencies:\n  - readers: [Check.lean]\n    inputs: [missing.txt]\n")
    with pytest.raises(DependencyDeclarationError, match=r"scripts/\.gv-dependencies\.yaml.*missing\.txt"):
        WorkflowGraph(repo, commit(repo))
