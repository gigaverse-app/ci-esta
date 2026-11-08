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


@pytest.fixture
def application(tmp_path: Path) -> tuple[Path, str]:
    """A Vite-style Bun workspace without node_modules: aliases, query imports, workspaces, preloads."""
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    write(tmp_path, "package.json", '{"name": "sample", "private": true, "workspaces": ["packages/*"]}\n')
    write(tmp_path, "tsconfig.json", '{"compilerOptions": {"paths": {"@lib/*": ["./src/*"]}}}\n')
    write(tmp_path, "bunfig.toml", '[test]\npreload = ["./setup.ts"]\n')
    write(tmp_path, "scripts/bunfig.ci.toml", '[test]\npreload = "./ci-setup.ts"\n')
    write(tmp_path, "scripts/ci-setup.ts", "globalThis.ci = true;\n")
    # The preload reaches a workspace package by name, which only a node_modules link resolves at runtime.
    write(tmp_path, "setup.ts", "import { kit } from '@sample/kit/setup';\nglobalThis.kit = kit;\n")
    write(tmp_path, "packages/kit/package.json", '{"name": "@sample/kit", "private": true}\n')
    write(tmp_path, "packages/kit/setup.ts", "export const kit = 1;\n")
    write(tmp_path, "packages/kit/format.ts", "export const format = (value: number) => `${value}`;\n")
    write(tmp_path, "src/alias.ts", "export const alias = 1;\n")
    for name in ("lazy", "side"):
        write(tmp_path, f"src/{name}.ts", f"export const {name} = 1;\n")
    write(tmp_path, "src/legacy.cjs", "module.exports = 1;\n")
    # Generated code is untracked, but what it imports still reaches the tests that import it.
    write(tmp_path, ".gitignore", "src/generated.ts\n")
    write(tmp_path, "src/generated.ts", "export { routes } from './routes';\n")
    write(tmp_path, "src/routes.ts", "export const routes = [];\n")
    write(tmp_path, "src/style.css", ".stage { color: red; }\n")
    write(tmp_path, "src/icon.svg", "<svg xmlns='http://www.w3.org/2000/svg'/>\n")
    # Both tests import `@lib/alias`, which Bun 1.3 then names only by its specifier.
    write(
        tmp_path,
        "tests/unit/assets.test.ts",
        TEST.format(
            imports="import { alias } from '@lib/alias';\nimport css from '../../src/style.css?raw';\n"
            "import { format } from '@sample/kit/format';\nconst legacy = require('../../src/legacy.cjs');\n"
            "import { routes } from '../../src/generated';"
        ),
    )
    write(
        tmp_path,
        "tests/feature/alias.test.ts",
        TEST.format(
            imports="import { alias } from '@lib/alias';\nimport Icon from '@lib/icon.svg?react';\n"
            "import '../../src/side';\nconst { lazy } = await import('../../src/lazy');"
        ),
    )
    return tmp_path, commit(tmp_path)


@pytest.mark.parametrize(
    ("path", "content", "expected"),
    [
        # A tsconfig `paths` alias, imported by both tests.
        ("src/alias.ts", "export const alias = 2;\n", {"unit": True, "feature": True}),
        # Query-suffixed imports name the file without the query, relative or aliased.
        ("src/style.css", ".stage { color: blue; }\n", {"unit": True, "feature": False}),
        ("src/icon.svg", "<svg xmlns='http://www.w3.org/2000/svg' width='1'/>\n", {"unit": False, "feature": True}),
        # A workspace package imported by name, with no node_modules link.
        ("packages/kit/format.ts", "export const format = String;\n", {"unit": True, "feature": False}),
        # `require`, side-effect and dynamic imports are edges too.
        ("src/legacy.cjs", "module.exports = 2;\n", {"unit": True, "feature": False}),
        ("src/side.ts", "export const side = 2;\n", {"unit": False, "feature": True}),
        ("src/lazy.ts", "export const lazy = 2;\n", {"unit": False, "feature": True}),
        ("src/routes.ts", "export const routes = [1];\n", {"unit": True, "feature": False}),
        # A preload runs before every test, so it and everything it bundles reach every Bun lane.
        ("setup.ts", "globalThis.kit = 2;\n", {"unit": True, "feature": True}),
        ("packages/kit/setup.ts", "export const kit = 2;\n", {"unit": True, "feature": True}),
        ("scripts/ci-setup.ts", "globalThis.ci = false;\n", {"unit": True, "feature": True}),
        # Any Bun configuration, including one a lane passes with `--config`.
        ("scripts/bunfig.ci.toml", "[test]\n", {"unit": True, "feature": True}),
    ],
)
def test_repository_imports_bun_resolves_without_node_modules(application, path, content, expected):
    repo, base = application
    write(repo, path, content)
    result = plan_work(repo, lanes(), base, commit(repo))
    assert result.lanes == expected, result.lane_reasons
    assert not any("fallback" in reason for reasons in result.lane_reasons.values() for reason in reasons)


def test_evidence_names_the_preload_and_what_it_bundles(application):
    repo, base = application
    write(repo, "packages/kit/setup.ts", "export const kit = 2;\n")
    result = plan_work(repo, lanes(), base, commit(repo))
    assert "Bun test preload: setup.ts (bundles packages/kit/setup.ts)" in result.lane_reasons["unit"]


def test_evidence_names_the_test_and_what_it_bundles(repository):
    repo, base = repository
    write(repo, "fixtures/notes.md", "# Changed\n")
    result = plan_work(repo, lanes(), base, commit(repo))
    assert "affected Bun test: tests/feature/b.test.ts (bundles fixtures/notes.md)" in result.lane_reasons["feature"]


def test_a_deleted_bun_test_still_runs_its_lane(repository):
    repo, base = repository
    (repo / "tests/unit/a.test.ts").unlink()
    assert plan_work(repo, lanes(), base, commit(repo)).lanes["unit"] is True


@pytest.mark.parametrize("broken", ["import", "query import", "preload", "executable"])
def test_a_graph_bun_cannot_build_runs_every_bun_lane(repository, broken):
    repo, base = repository
    if broken == "import":
        write(repo, "src/b.ts", "import { gone } from './missing';\nexport const b = gone;\n")
    elif broken == "query import":
        write(repo, "src/b.ts", "import gone from './missing.css?raw';\nexport const b = gone;\n")
    elif broken == "preload":
        write(repo, "bunfig.toml", '[test]\npreload = ["./missing-setup.ts"]\n')
        # Committed before the base, so the preload, not a changed configuration, is what fails.
        base = commit(repo)
        write(repo, "src/b.ts", "export const b = 3;\n")
    else:
        write(repo, "src/a.ts", "export const a = 3;\n")
    head = commit(repo)
    result = plan_work(repo, lanes(), base, head, bun="no-such-bun" if broken == "executable" else "bun")
    assert result.lanes == {"unit": True, "feature": True}
    assert all("Bun module graph unavailable" in reasons[0] for reasons in result.lane_reasons.values())


def test_the_bun_environment_rule_can_be_switched_off(repository):
    from ci_esta.testing.lane_rules import effective

    repo, base = repository
    write(repo, "package.json", '{"name": "sample", "private": false}\n')
    head = commit(repo)
    assert plan_work(repo, lanes(), base, head).lanes == {"unit": True, "feature": True}
    rules = effective([], ["bun-environment"])
    assert plan_work(repo, lanes(), base, head, rules=rules).lanes == {"unit": False, "feature": False}
