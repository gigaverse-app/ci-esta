"""Bun tests reach lanes through Bun's module graph, on real Git commits and a real Bun."""

import shutil
import subprocess
from pathlib import Path

import pytest
from pytest_selective.ci import Lane, LaneConfig
from pytest_selective.impact_models import ImpactConfig

from ci_esta.testing.work_plan import plan_work
from tests.testing.git_repo import commit, write

pytestmark = pytest.mark.skipif(
    shutil.which("bun") is None, reason="native Bun planning runs in the required Runtime contracts job"
)

TEST = "import {{ expect, test }} from 'bun:test';\n{imports}\ntest('works', () => expect(1).toBe(1));\n"


def lanes() -> LaneConfig:
    return LaneConfig(
        graph=ImpactConfig(module_roots=["."], test_roots=["tests"]),
        lanes={"unit": Lane(roots=["tests/unit"]), "feature": Lane(roots=["tests/feature"])},
        global_inputs=["uv.lock"],
    )


@pytest.fixture
def repository(tmp_path: Path) -> tuple[Path, str]:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    write(tmp_path, "package.json", '{"name": "sample", "private": true}\n')
    write(tmp_path, "src/a.ts", "export const a = 1;\n")
    write(tmp_path, "src/b.ts", "import { a } from './a';\nexport const b = a + 1;\n")
    write(tmp_path, "tests/unit/a.test.ts", TEST.format(imports="import { a } from '../../src/a';"))
    write(
        tmp_path,
        "tests/feature/b.test.ts",
        TEST.format(
            imports="import { b } from '../../src/b';\nimport notes from '../../fixtures/notes.md' with { type: 'text' };"
        ),
    )
    write(tmp_path, "fixtures/notes.md", "# Read by the feature test\n")
    write(tmp_path, "fixtures/other.md", "# Read by nothing\n")
    write(tmp_path, "README.md", "# Sample\n")
    return tmp_path, commit(tmp_path)


@pytest.mark.parametrize(
    ("path", "content", "expected"),
    [
        # Nothing bundles these, so they select nothing.
        ("README.md", "# Changed\n", {"unit": False, "feature": False}),
        ("fixtures/other.md", "# Changed\n", {"unit": False, "feature": False}),
        # Imports and text imports, followed transitively.
        ("src/a.ts", "export const a = 2;\n", {"unit": True, "feature": True}),
        ("src/b.ts", "import { a } from './a';\nexport const b = a + 2;\n", {"unit": False, "feature": True}),
        ("fixtures/notes.md", "# Changed\n", {"unit": False, "feature": True}),
        # Bun's environment reaches every Bun lane.
        ("package.json", '{"name": "sample", "private": false}\n', {"unit": True, "feature": True}),
    ],
)
def test_bun_tests_reach_lanes_through_the_module_graph(repository, path, content, expected):
    repo, base = repository
    write(repo, path, content)
    result = plan_work(repo, lanes(), base, commit(repo))
    assert result.lanes == expected, result.lane_reasons


def test_evidence_names_the_test_and_what_it_bundles(repository):
    repo, base = repository
    write(repo, "fixtures/notes.md", "# Changed\n")
    result = plan_work(repo, lanes(), base, commit(repo))
    assert "affected Bun test: tests/feature/b.test.ts (bundles fixtures/notes.md)" in result.lane_reasons["feature"]


def test_a_deleted_bun_test_still_runs_its_lane(repository):
    repo, base = repository
    (repo / "tests/unit/a.test.ts").unlink()
    assert plan_work(repo, lanes(), base, commit(repo)).lanes["unit"] is True


@pytest.mark.parametrize("broken", ["import", "executable"])
def test_a_graph_bun_cannot_build_runs_every_bun_lane(repository, broken):
    repo, base = repository
    if broken == "import":
        write(repo, "src/b.ts", "import { gone } from './missing';\nexport const b = gone;\n")
    else:
        write(repo, "src/a.ts", "export const a = 3;\n")
    head = commit(repo)
    result = plan_work(repo, lanes(), base, head, bun="bun" if broken == "import" else "no-such-bun")
    assert result.lanes == {"unit": True, "feature": True}
    assert all("Bun module graph unavailable" in reasons[0] for reasons in result.lane_reasons.values())
