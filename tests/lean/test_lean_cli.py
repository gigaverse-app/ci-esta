import io
import subprocess

import pytest

from ci_esta.lean import cli, queue_report


@pytest.mark.parametrize("command", ["preflight", "queue", "retry", "statements"])
def test_subcommand_help(command, capsys):
    with pytest.raises(SystemExit) as error:
        cli.main([command, "--help"])

    assert error.value.code == 0
    assert "usage:" in capsys.readouterr().out


def test_queue_sample_excludes_unknown_timings():
    assert queue_report.summary([None, 1, 2, 4]) == {
        "n": 3,
        "median_s": 2,
        "p95_s": 4,
    }


def test_retry_reads_lake_and_github_logs_in_diagnostic_order(tmp_path, capsys):
    src = tmp_path / "src"
    src.mkdir()
    for name in ("Second.lean", "First.lean", "Missing.lean"):
        (src / name).touch()
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "add", "src"], check=True)
    (src / "Missing.lean").unlink()
    (src / "Untracked.lean").touch()
    log = tmp_path / "lake.log"
    log.write_text(
        "Lake\tBuild\t2026-11-26T12:36:58.5406831Z \x1b[31merror:\x1b[0m src/Second.lean:302:17: bad\n"
        "error: ./src/First.lean:1:1: bad\n"
        "error: src/Second.lean:45:1: bad again\n"
        "warning: src/First.lean:2:1: warning\n"
        "error: .lake/packages/external/Dependency.lean:1:1: bad\n"
        "error: src/Missing.lean:1:1: removed\n"
        "error: src/Untracked.lean:1:1: untracked\n"
        "error: build failed\n",
        encoding="utf-8",
    )
    assert cli.main(["retry", str(log), "--repo", str(src), "--source-root", "src"]) == 0
    assert capsys.readouterr().out == "lake build +Second +First\n"


def test_retry_with_no_project_diagnostics_prints_no_command(tmp_path, monkeypatch, capsys):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    monkeypatch.setattr("sys.stdin", io.StringIO("error: build failed\n"))
    assert cli.main(["retry", "-", "--repo", str(tmp_path)]) == 0
    output = capsys.readouterr()
    assert output.out == ""
    assert "no errors matched" in output.err


def _project(root, lakefile, sources):
    root.mkdir(parents=True, exist_ok=True)
    (root / "lakefile.toml").write_text(lakefile, encoding="utf-8")
    for source in sources:
        (root / source).parent.mkdir(parents=True, exist_ok=True)
        (root / source).touch()


def _commit_all(repo):
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)


# Lines from leanprover-community/riemann-hypothesis job 139912708645, whose lakefile sets srcDir = "src".
GITHUB_LOG = (
    "﻿2026-11-26T12:34:42.1510284Z Current runner version: '2.338.2'\n"
    "2026-11-26T12:36:58.5394843Z ✖ [21301/22653] Building Lib.DiscreteSeries.Haar.CayleyChart (4.2s)\n"
    "2026-11-26T12:36:58.5406831Z error: src/Lib/DiscreteSeries/Haar/CayleyChart.lean:302:17: failed to synthesize\n"
    "2026-11-26T12:37:13.6157792Z ✖ [21429/22653] Building Lib.Adelic.Adeles.IdeleModulus (4.1s)\n"
    "2026-11-26T12:37:13.6230869Z error: src/Lib/Adelic/Adeles/IdeleModulus.lean:388:8: failed to synthesize\n"
    "2026-11-26T12:39:14.5969051Z Some required targets logged failures:\n"
    "2026-11-26T12:39:14.5969335Z - Lib.DiscreteSeries.Haar.CayleyChart\n"
    "2026-11-26T12:39:14.5969599Z - Lib.Adelic.Adeles.IdeleModulus\n"
    "2026-11-26T12:39:14.5972650Z error: build failed\n"
)
SRC_DIR_LAKEFILE = 'name = "GRH"\nsrcDir = "src"\n\n[[lean_lib]]\nname = "Challenge"\nsrcDir = ".."\n'
SRC_DIR_SOURCES = ["src/Lib/DiscreteSeries/Haar/CayleyChart.lean", "src/Lib/Adelic/Adeles/IdeleModulus.lean"]


def test_retry_names_modules_under_the_lake_source_directory_by_default(tmp_path, capsys):
    _project(tmp_path, SRC_DIR_LAKEFILE, SRC_DIR_SOURCES)
    _commit_all(tmp_path)
    log = tmp_path / "job.log"
    log.write_text(GITHUB_LOG, encoding="utf-8")

    assert cli.main(["retry", str(log), "--repo", str(tmp_path)]) == 0

    assert capsys.readouterr().out == "lake build +Lib.DiscreteSeries.Haar.CayleyChart +Lib.Adelic.Adeles.IdeleModulus\n"


def test_retry_reads_the_source_directory_from_the_lakefile_for_bare_diagnostics(tmp_path, capsys):
    _project(tmp_path, SRC_DIR_LAKEFILE, [*SRC_DIR_SOURCES, "Challenge.lean"])
    _commit_all(tmp_path)
    log = tmp_path / "errors.log"
    log.write_text(
        "error: src/Lib/Adelic/Adeles/IdeleModulus.lean:388:8: failed to synthesize\n"
        "error: Challenge.lean:1:0: bad\n",
        encoding="utf-8",
    )

    assert cli.main(["retry", str(log), "--repo", str(tmp_path / "src" / "Lib")]) == 0

    assert capsys.readouterr().out == "lake build +Lib.Adelic.Adeles.IdeleModulus +Challenge\n"


# Lines Lake 5.0.0 (Lean 4.37.0-rc1) printed for a package in a subdirectory of its Git checkout,
# shortened; `Toy.Killed` ran `IO.Process.exit 137` to stand in for an out-of-memory kill.
SUBDIRECTORY_LOG = """\
✖ [3/21] Running Toy.Missing
error: no such file or directory (error code: 2)
  file: /work/proj/Toy/Missing.lean
✖ [5/21] Running Toy.BadImport
error: Toy/BadImport.lean: bad import 'Toy.Missing'
✖ [9/21] Building Toy.«Sp ace».Mod (295ms)
error: Toy/Sp ace/Mod.lean:1:24: Type mismatch
✔ [11/21] Built Toy.Good (347ms)
✖ [13/21] Building Toy.Prime' (311ms)
error: Toy/Prime'.lean:1:24: Type mismatch
✖ [17/21] Building Toy.Killed
error: Lean exited with code 137
✖ [21/21] Running toy/Toy:default
error: Toy: some modules have bad imports or could not be read
Some required targets logged failures:
- Toy.Missing
- Toy.BadImport
- Toy.«Sp ace».Mod
- Toy.Prime'
- Toy.Killed
- toy/Toy:default
error: build failed
"""
SUBDIRECTORY_SOURCES = ["Toy/BadImport.lean", "Toy/Sp ace/Mod.lean", "Toy/Prime'.lean", "Toy/Killed.lean", "Toy/Good.lean"]


def test_retry_keeps_failures_without_positions_in_a_package_below_the_git_root(tmp_path, capsys):
    project = tmp_path / "proj"
    _project(project, 'name = "toy"\n', SUBDIRECTORY_SOURCES)
    _commit_all(tmp_path)
    log = tmp_path / "lake.log"
    log.write_text(SUBDIRECTORY_LOG, encoding="utf-8")

    assert cli.main(["retry", str(log), "--repo", str(project)]) == 0

    output = capsys.readouterr()
    assert output.out == "lake build +Toy.BadImport '+Toy.«Sp ace».Mod' '+Toy.Prime'\"'\"'' +Toy.Killed\n"
    assert "Toy.Missing" in output.err
    assert "toy/Toy:default" not in output.err


def test_retry_quotes_path_components_that_are_not_identifiers(tmp_path, capsys):
    project = tmp_path / "proj"
    _project(project, 'name = "toy"\n', ["Toy/Sp ace/Mod.lean", "Toy/1x/a-b.lean"])
    _commit_all(tmp_path)
    log = tmp_path / "errors.log"
    log.write_text(
        "error: Toy/Sp ace/Mod.lean:1:24: Type mismatch\nerror: Toy\\1x\\a-b.lean:1:24: Type mismatch\r\n",
        encoding="utf-8",
    )

    assert cli.main(["retry", str(log), "--repo", str(project)]) == 0

    assert capsys.readouterr().out == "lake build '+Toy.«Sp ace».Mod' '+Toy.«1x».«a-b»'\n"
