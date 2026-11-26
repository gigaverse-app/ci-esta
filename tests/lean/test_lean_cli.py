import pytest

from ci_esta.lean import cli, queue_report


@pytest.mark.parametrize("command", ["preflight", "queue", "statements"])
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
