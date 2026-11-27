import io
import subprocess

import pytest

from ci_esta.lean import cli, queue_report


@pytest.mark.parametrize("command", ["preflight", "queue", "retry", "statements", "compare"])
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
