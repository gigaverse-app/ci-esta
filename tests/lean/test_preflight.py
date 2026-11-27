"""Exercise the planner using real Git trees and Lean's import parser."""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from ci_esta.lean import preflight
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


def test_previous_failure_accepts_the_module_name_lake_prints(repo):
    base = commit(repo)
    write(repo, "README.md", "# Changed\n")
    result = plan(repo, base, commit(repo), LEAN, ["Caller", "./src/Independent.lean"])
    assert result["retry_command"] == ["lake", "build", "+Caller", "+Independent"]


@pytest.mark.parametrize("arguments", [["HEAD", "HEAD"], ["HEAD~1", "HEAD"]])
def test_previous_failure_naming_no_source_is_an_error_not_an_empty_plan(repo, arguments, capsys):
    commit(repo)
    write(repo, "src/Base.lean", "def x := 1\n")
    commit(repo)

    with pytest.raises(SystemExit) as error:
        preflight.main([*arguments, "--repo", str(repo), "--lean", LEAN, "--previous-failure", "Caller.lean"])

    assert error.value.code == 2
    output = capsys.readouterr()
    assert output.out == ""
    assert "Caller.lean" in output.err


def test_previous_failure_removed_at_head_is_not_retried(repo):
    base = commit(repo)
    (repo / "src/Independent.lean").unlink()
    result = plan(repo, base, commit(repo), LEAN, ["src/Independent.lean"])
    assert result["retry_command"] == []


def test_non_ascii_module_names_keep_their_importers_under_a_non_utf8_locale(repo):
    write(repo, "src/\u00dcn\u00ef.lean", "def u := 0\n")
    write(repo, "src/Reader.lean", "import \u00dcn\u00ef\n")
    base = commit(repo)
    write(repo, "src/\u00dcn\u00ef.lean", "def u := 1\n")
    commit(repo)
    environment = os.environ | {"LC_ALL": "C", "PYTHONCOERCECLOCALE": "0", "PYTHONUTF8": "0", "PYTHONIOENCODING": "utf-8"}

    output = subprocess.check_output(
        [sys.executable, "-m", "ci_esta.lean.preflight", base, "HEAD", "--repo", str(repo), "--lean", LEAN],
        env=environment,
    )

    assert json.loads(output)["command"] == ["lake", "build", "+Reader"]


def test_uncommitted_work_is_reported_beside_a_plan_for_the_checked_out_commit(repo, capsys):
    base = commit(repo)
    write(repo, "src/Base.lean", "def x := 1\n")
    write(repo, "src/New.lean", "def z := 0\n")

    preflight.main([base, "--repo", str(repo), "--lean", LEAN])

    output = capsys.readouterr()
    result = json.loads(output.out)
    assert result["mode"] == "none"
    assert result["uncommitted"] == ["src/Base.lean", "src/New.lean"]
    assert "uncommitted" in output.err


def test_a_plan_for_another_commit_ignores_the_working_tree(repo, capsys):
    base = commit(repo)
    write(repo, "README.md", "# Changed\n")
    commit(repo)
    write(repo, "src/Base.lean", "def x := 1\n")

    preflight.main([base, base, "--repo", str(repo), "--lean", LEAN])

    assert "uncommitted" not in json.loads(capsys.readouterr().out)


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
