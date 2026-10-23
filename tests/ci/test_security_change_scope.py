"""Security admission must prove irrelevant inputs before skipping work."""

import json
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
MODULE = ROOT / "actions/resolve-security-trigger/scope.cjs"


def scope(files: object, *, complete: bool = True, excluded: tuple[str, ...] = ()) -> dict[str, bool]:
    script = (
        "const m=require(process.argv[1]); console.log(JSON.stringify(m.classifyChanges(JSON.parse(process.argv[2]))));"
    )
    result = subprocess.run(
        [
            "node",
            "-e",
            script,
            str(MODULE),
            json.dumps(
                {
                    "files": files,
                    "sourceExcludedPaths": excluded,
                    "complete": complete,
                    "dependencyPatterns": ["uv.lock", "deployment/Dockerfile", ".github/services/"],
                    "ignoredPaths": [".github/backend-common-bump.json"],
                    "prosePatterns": ["docs/**/*.md", "plugins/**/SKILL.md"],
                }
            ),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(result.stdout)


@pytest.mark.parametrize(
    "path,dependency,source",
    [
        ("plugins/gv-cli/skills/gv-cli/SKILL.md", False, False),
        ("docs/guide.md", False, False),
        ("src/prompts/system.md", False, True),
        ("src/service.py", False, True),
        ("uv.lock", True, True),
        (".github/services/service.yaml", True, True),
        ("deployment/Dockerfile", True, True),
    ],
)
def test_changed_inputs_select_only_relevant_security_work(path: str, dependency: bool, source: bool) -> None:
    assert scope([{"filename": path, "status": "modified"}]) == {
        "depsChanged": dependency,
        "semgrepChanged": True,
        "sourceChanged": source,
    }


@pytest.mark.parametrize("files", [None, [{"status": "modified"}], [{"filename": "docs/a.md"}]])
def test_invalid_evidence_cannot_skip_security(files: object) -> None:
    assert all(scope(files).values())


def test_incomplete_evidence_cannot_skip_security() -> None:
    assert all(scope([], complete=False).values())


def test_rename_out_of_dependency_path_invalidates_inventory() -> None:
    result = scope([{"filename": "docs/old.md", "previous_filename": "uv.lock", "status": "renamed"}])
    assert result["depsChanged"]
    assert result["sourceChanged"]


def test_removed_source_cannot_introduce_findings_but_removed_dependency_changes_inventory() -> None:
    assert scope([{"filename": "uv.lock", "status": "removed"}]) == {
        "depsChanged": True,
        "semgrepChanged": False,
        "sourceChanged": False,
    }


def test_empty_or_generated_only_delta_does_not_allocate_scanners() -> None:
    assert not any(scope([]).values())
    assert not any(scope([{"filename": ".github/backend-common-bump.json", "status": "modified"}]).values())


@pytest.mark.parametrize(
    "path,expected",
    [(".github/workflows/check.yaml", False), (".github-other/check.yaml", True), ("src/service.py", True)],
)
def test_ci_owner_exclusion_does_not_allocate_duplicate_source_scanner(path: str, expected: bool) -> None:
    result = scope([{"filename": path, "status": "modified"}], excluded=(".github/workflows",))
    assert result["semgrepChanged"] is expected
