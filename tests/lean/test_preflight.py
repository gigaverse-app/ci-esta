"""Exercise the planner using real Git trees and Lean's import parser."""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from ci_esta.lean import cli, preflight
from ci_esta.lean.preflight import plan

LEAN = shutil.which("lean")
pytestmark = pytest.mark.skipif(LEAN is None, reason="Lean is required")


def git(repo, *args):
    return subprocess.check_output(["git", "-C", str(repo), *args], text=True).strip()


def write(repo, path, text):
    output = repo / path
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(text, encoding="utf-8")


def commit(repo):
    git(repo, "add", "-A")
    git(
        repo,
        "-c",
        "user.name=Fixture",
        "-c",
        "user.email=fixture@example.invalid",
        "commit",
        "--quiet",
        "-m",
        "fixture",
    )
    return git(repo, "rev-parse", "HEAD")


@pytest.fixture
def repo(tmp_path):
    git(tmp_path, "init", "--quiet")
    write(tmp_path, "src/Base.lean", "def x := 0\n")
    write(tmp_path, "src/Caller.lean", "/- import Fake -/\nimport Base\n")
    write(tmp_path, "src/Final.lean", "module\npublic import Caller\n")
    write(tmp_path, "src/Independent.lean", "def y := 0\n")
    write(tmp_path, "README.md", "# Original\n")
    return tmp_path


def test_reverse_imports_use_lean_syntax_and_choose_consumers(repo):
    base = commit(repo)
    write(repo, "src/Base.lean", "def x := 1\n")
    result = plan(repo, base, commit(repo), LEAN)
    assert result["command"] == ["lake", "build", "+Final"]
    assert result["modules"][-1]["because"] == [
        "src/Base.lean",
        "src/Caller.lean",
        "src/Final.lean",
    ]


def test_docs_are_deferrable_unless_a_reader_declares_them(repo):
    write(
        repo,
        "src/.gv-dependencies.yaml",
        """
dependencies:
  - readers: [Independent.lean]
    inputs: [//README.md]
    kind: content
""",
    )
    base = commit(repo)
    write(repo, "README.md", "# Changed\n")
    result = plan(repo, base, commit(repo), LEAN)
    assert result["command"] == ["lake", "build", "+Independent"]
    assert result["modules"][0]["because"] == ["README.md", "src/Independent.lean"]


def test_unknown_inputs_force_full_build(repo):
    base = commit(repo)
    write(repo, "lean-toolchain", "some-pin\n")
    assert plan(repo, base, commit(repo), LEAN)["command"] == ["lake", "build"]


def test_deleted_import_still_reaches_its_consumers(repo):
    base = commit(repo)
    (repo / "src/Base.lean").unlink()
    assert plan(repo, base, commit(repo), LEAN)["command"] == [
        "lake",
        "build",
        "+Final",
    ]


def test_previous_failure_retries_even_for_an_unrelated_edit(repo):
    base = commit(repo)
    write(repo, "README.md", "# Changed\n")
    result = plan(repo, base, commit(repo), LEAN, ["src/Caller.lean"])
    assert result["retry_command"] == ["lake", "build", "+Caller"]
    assert result["command"] == ["lake", "build", "+Final"]


def test_renamed_binders_match_but_implicit_binders_do_not(tmp_path):
    source = Path(__file__).with_name("fixtures") / "Example.lean"
    (tmp_path / "Example.lean").write_bytes(source.read_bytes())
    subprocess.run([LEAN, "-o", "Example.olean", "Example.lean"], cwd=tmp_path, check=True)
    output = subprocess.check_output(
        [
            LEAN,
            "--run",
            str(Path(preflight.__file__).with_name("TheoremMatches.lean").resolve()),
            "Example",
        ],
        cwd=tmp_path,
        env=os.environ | {"LEAN_PATH": str(tmp_path)},
        text=True,
    )
    assert json.loads(output) == [
        [
            {"module": "Example", "theorem": "left"},
            {"module": "Example", "theorem": "right"},
        ]
    ]


def test_compare_reports_changed_and_missing_declaration_types(tmp_path, capfd):
    source = tmp_path / "Proof.lean"
    for artifact, text in [
        (
            "before.olean",
            "theorem stable (n : Nat) : n = n := rfl\n"
            "theorem visibility (n : Nat) : n = n := rfl\n"
            "theorem removed : True := True.intro\n",
        ),
        (
            "after.olean",
            "theorem stable (m : Nat) : m = m := by rfl\n"
            "theorem visibility {n : Nat} : n = n := rfl\n"
            "theorem added : True := True.intro\n",
        ),
    ]:
        source.write_text(text, encoding="utf-8")
        subprocess.run([LEAN, "-o", artifact, source.name], cwd=tmp_path, check=True)
    args = ["compare", str(tmp_path / "before.olean"), str(tmp_path / "after.olean"), "--lean", LEAN]
    assert cli.main([*args, "stable"]) == 0
    assert json.loads(capfd.readouterr().out) == [{"declaration": "stable", "status": "unchanged"}]
    assert cli.main([*args, "visibility", "removed", "added", "missing"]) == 1
    assert json.loads(capfd.readouterr().out) == [
        {"declaration": "visibility", "status": "changed"},
        {"declaration": "removed", "status": "missing-after"},
        {"declaration": "added", "status": "missing-before"},
        {"declaration": "missing", "status": "missing-both"},
    ]
