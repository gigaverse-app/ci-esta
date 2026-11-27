"""Exercise the planner using real Git trees and Lean's import parser."""

import json
import os
import shutil
import subprocess
import sys
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


def test_module_names_that_need_quoting_keep_their_importers_and_are_spelled_for_lake(repo):
    write(repo, "src/Lib/My-File.lean", "def a := 0\n")
    write(repo, "src/Lib/2024.lean", "def b := 0\n")
    write(repo, "src/Reader.lean", "import Lib.\u00abMy-File\u00bb\nimport Lib.\u00ab2024\u00bb\n")
    base = commit(repo)
    write(repo, "src/Lib/My-File.lean", "def a := 1\n")
    head = commit(repo)

    assert plan(repo, base, head, LEAN)["command"] == ["lake", "build", "+Reader"]
    for failure in ("Lib.\u00abMy-File\u00bb", "Lib.My-File", "src/Lib/My-File.lean"):
        result = plan(repo, base, head, LEAN, [failure])
        assert result["retry_command"] == ["lake", "build", "+Lib.\u00abMy-File\u00bb"]
    write(repo, "src/Lib/2024.lean", "def b := 1\n")
    (repo / "src/Reader.lean").unlink()
    assert plan(repo, head, commit(repo), LEAN)["command"] == ["lake", "build", "+Lib.\u00ab2024\u00bb"]


LIBRARY_IN_PACKAGE_ROOT = {"Lib.lean": "import Lib.A\n", "Lib/A.lean": "def x := 0\n"}


@pytest.mark.parametrize(
    ("lakefile", "sources", "changed", "module"),
    [
        (None, LIBRARY_IN_PACKAGE_ROOT, "Lib/A.lean", "Lib.A"),
        ('name = "p"\n[[lean_lib]]\nname = "Lib"\n', LIBRARY_IN_PACKAGE_ROOT, "Lib/A.lean", "Lib.A"),
        (
            'name = "p"\nsrcDir = "lean"\n[[lean_lib]]\nname = "Lib"\n',
            {"lean/Lib.lean": "import Lib.A\n", "lean/Lib/A.lean": "def x := 0\n"},
            "lean/Lib/A.lean",
            "Lib.A",
        ),
    ],
)
def test_sources_are_found_in_the_lake_source_directory(tmp_path, lakefile, sources, changed, module):
    git(tmp_path, "init", "--quiet")
    if lakefile:
        write(tmp_path, "lakefile.toml", lakefile)
    for path, text in sources.items():
        write(tmp_path, path, text)
    write(tmp_path, "README.md", "# Original\n")
    base = commit(tmp_path)
    write(tmp_path, "README.md", "# Changed\n")
    head = commit(tmp_path)

    assert plan(tmp_path, base, head, LEAN, [module])["retry_command"] == ["lake", "build", f"+{module}"]
    write(tmp_path, changed, "def x := 1\n")
    assert plan(tmp_path, head, commit(tmp_path), LEAN)["command"] == ["lake", "build", "+Lib"]


def test_a_lean_lakefile_that_sets_its_own_source_directory_still_gets_a_full_build(tmp_path):
    git(tmp_path, "init", "--quiet")
    write(tmp_path, "lakefile.lean", 'import Lake\nopen Lake DSL\npackage p where\n  srcDir := "lean"\n')
    write(tmp_path, "lean/Lib.lean", "def x := 0\n")
    base = commit(tmp_path)
    write(tmp_path, "lean/Lib.lean", "def x := 1\n")

    assert plan(tmp_path, base, commit(tmp_path), LEAN)["command"] == ["lake", "build"]


def test_a_plan_with_nothing_to_build_has_the_same_keys_with_and_without_a_diff(repo):
    base = commit(repo)
    write(repo, "README.md", "# Changed\n")
    head = commit(repo)

    unchanged, documentation = plan(repo, head, head, LEAN), plan(repo, base, head, LEAN)

    assert unchanged["mode"] == documentation["mode"] == "none"
    assert unchanged.keys() == documentation.keys()
    assert unchanged["command"] == unchanged["retry_command"] == []


def test_a_bare_repository_has_no_uncommitted_work_and_keeps_its_plan(repo, tmp_path_factory, capsys):
    base = commit(repo)
    write(repo, "src/Base.lean", "def x := 1\n")
    commit(repo)
    bare = tmp_path_factory.mktemp("bare") / "repo.git"
    git(repo, "clone", "--quiet", "--bare", str(repo), str(bare))

    preflight.main([base, "HEAD", "--repo", str(bare), "--lean", LEAN])

    result = json.loads(capsys.readouterr().out)
    assert result["command"] == ["lake", "build", "+Final"]
    assert "uncommitted" not in result


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


def test_compare_normalizes_a_deeply_shared_type_once_per_distinct_subterm(tmp_path):
    # `And t t` nested 64 deep has 65 distinct subterms and 2^64 paths through them.
    (tmp_path / "Shared.lean").write_text(
        "import Lean\n"
        "open Lean Elab Command\n"
        "def nested : Nat \u2192 Expr\n"
        "  | 0 => mkConst ``True\n"
        "  | n + 1 => let t := nested n; mkApp2 (mkConst ``And) t t\n"
        'elab "declare_shared" : command =>\n'
        "  liftCoreM <| addDecl <| .axiomDecl\n"
        "    { name := `shared, levelParams := [], type := nested 64, isUnsafe := false }\n"
        "declare_shared\n",
        encoding="utf-8",
    )
    subprocess.run([LEAN, "-o", "Shared.olean", "Shared.lean"], cwd=tmp_path, check=True)
    scanner = Path(preflight.__file__).with_name("TheoremMatches.lean").resolve()

    output = subprocess.check_output(
        [LEAN, "--run", str(scanner), "--compare", "Shared.olean", "Shared.olean", "shared"],
        cwd=tmp_path,
        text=True,
        timeout=60,
    )

    assert json.loads(output) == [{"declaration": "shared", "status": "unchanged"}]
