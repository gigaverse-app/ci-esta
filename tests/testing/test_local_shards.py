import sys
from pathlib import Path

import pytest

from ci_esta.testing.local_shards import LocalShardRunConfig, run_local_shards

SHARD_COUNT = 3
FAILING_SHARD = 2


def _write_worker(path: Path, *, fail_one: bool) -> None:
    failure = f"raise SystemExit(9 if shard == {FAILING_SHARD} else 0)" if fail_one else "raise SystemExit(0)"
    path.write_text(
        "\n".join(
            (
                "import os",
                "from pathlib import Path",
                'shard = int(os.environ["GV_PYTEST_SHARD_INDEX"])',
                'count = int(os.environ["GV_PYTEST_SHARD_COUNT"])',
                'output = Path(os.environ["SHARD_TEST_OUTPUT"])',
                'output.joinpath(f"{shard}-of-{count}").write_text("ran")',
                'print(f"worker={shard}/{count}")',
                failure,
            )
        )
        + "\n"
    )


def _config(tmp_path: Path, worker: Path) -> LocalShardRunConfig:
    return LocalShardRunConfig(
        shard_count=SHARD_COUNT,
        command=[sys.executable, str(worker)],
        log_dir=tmp_path / "logs",
        environment={"SHARD_TEST_OUTPUT": str(tmp_path)},
    )


def test_local_shards_run_every_index_once_with_isolated_logs(tmp_path: Path) -> None:
    """INVARIANT: every local shard receives one stable identity and log."""
    worker = tmp_path / "worker.py"
    _write_worker(worker, fail_one=False)

    result = run_local_shards(_config(tmp_path, worker))

    assert result == 0
    for shard in range(1, SHARD_COUNT + 1):
        assert (tmp_path / f"{shard}-of-{SHARD_COUNT}").read_text() == "ran"
        assert f"worker={shard}/{SHARD_COUNT}" in (tmp_path / "logs" / f"group-{shard}.log").read_text()


def test_local_shards_wait_for_all_processes_and_report_any_failure(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """INVARIANT: one failed shard fails the aggregate without losing siblings."""
    worker = tmp_path / "worker.py"
    _write_worker(worker, fail_one=True)

    result = run_local_shards(_config(tmp_path, worker))

    assert result == 1
    assert {path.name for path in tmp_path.glob(f"*-of-{SHARD_COUNT}")} == {
        f"{shard}-of-{SHARD_COUNT}" for shard in range(1, SHARD_COUNT + 1)
    }
    output = capsys.readouterr().out
    assert f"Shard {FAILING_SHARD}/{SHARD_COUNT} failed" in output
    assert f"worker={FAILING_SHARD}/{SHARD_COUNT}" in output
