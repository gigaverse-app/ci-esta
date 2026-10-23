import json
import subprocess
import sys
import time
from pathlib import Path

import pytest
from pydantic import ValidationError

from ci_esta.testing.cli import main
from ci_esta.testing.local_shards import LocalShardRunConfig, run_local_shards

SHARD_COUNT = 3
FAILING_SHARD = 2
LIVE_REPORT_DEADLINE_SECONDS = 5


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


@pytest.mark.parametrize("fail_one", [False, True])
def test_shard_measurements_cover_real_processes_and_keep_source_identity(tmp_path, monkeypatch, fail_one):
    worker = tmp_path / "worker.py"
    _write_worker(worker, fail_one=fail_one)
    monkeypatch.setenv("GITHUB_RUN_ID", "431")
    monkeypatch.setenv("GITHUB_RUN_ATTEMPT", "2")
    monkeypatch.setenv("GITHUB_SHA", "b" * 40)  # Checkout merge differs from the run's PR head.
    event = tmp_path / "event.json"
    event.write_text(json.dumps({"pull_request": {"head": {"sha": "a" * 40}}}))
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(event))
    monkeypatch.setenv("GITHUB_JOB", "tests")
    config = _config(tmp_path, worker)
    assert run_local_shards(config) == int(fail_one)
    data = json.loads((config.log_dir / "ci-esta-shards.json").read_text())
    assert (data["run_id"], data["run_attempt"], data["head_sha"]) == (431, 2, "a" * 40)
    assert data["configured_shards"] == SHARD_COUNT
    assert {item["index"] for item in data["shards"]} == {1, 2, 3}
    assert all(0 <= item["start_seconds"] < item["end_seconds"] for item in data["shards"])
    assert {item["index"] for item in data["shards"] if item["exit_code"]} == ({2} if fail_one else set())


@pytest.mark.parametrize("sibling_status", [0, 9])
def test_live_reports_survive_a_blocked_first_shard(tmp_path: Path, sibling_status: int) -> None:
    """A blocked first shard cannot hide sibling results or its own diagnostics."""
    worker = tmp_path / "worker.py"
    release = tmp_path / "release"
    worker.write_text(
        "import os, pathlib, time\n"
        "shard = int(os.environ['GV_PYTEST_SHARD_INDEX'])\n"
        "if shard == 1:\n"
        "    print('watchdog diagnostic from blocked shard', flush=True)\n"
        f"    while not pathlib.Path({str(release)!r}).exists():\n"
        "        time.sleep(0.02)\n"
        f"raise SystemExit({sibling_status} if shard == 2 else 0)\n"
    )
    launcher = (
        "from pathlib import Path\n"
        "from ci_esta.testing.local_shards import LocalShardRunConfig, run_local_shards\n"
        "raise SystemExit(run_local_shards(LocalShardRunConfig("
        f"shard_count=2, command={[sys.executable, str(worker)]!r}, "
        f"log_dir=Path({str(tmp_path / 'logs')!r}), progress_interval_seconds=0.1)))\n"
    )
    report = tmp_path / "runner.log"
    sibling_result = "passed" if sibling_status == 0 else "failed (exit 9)"
    with report.open("w") as output, subprocess.Popen(
        [sys.executable, "-c", launcher], stdout=output, stderr=subprocess.STDOUT
    ) as process:
        try:
            deadline = time.monotonic() + LIVE_REPORT_DEADLINE_SECONDS
            while time.monotonic() < deadline:
                observed = report.read_text()
                if f"Shard 2/2 {sibling_result}" in observed and "watchdog diagnostic" in observed:
                    break
                time.sleep(0.02)
            assert process.poll() is None, observed
            assert f"Shard 2/2 {sibling_result}" in observed
            assert "Shard 1/2 still running" in observed
            assert "watchdog diagnostic from blocked shard" in observed
        finally:
            release.touch()
            process.wait(timeout=LIVE_REPORT_DEADLINE_SECONDS)
    assert process.returncode == int(sibling_status != 0)


def test_two_runner_ranges_execute_the_global_inventory_once(tmp_path: Path) -> None:
    worker = tmp_path / "worker.py"
    _write_worker(worker, fail_one=False)
    for first, last in [(1, 1), (2, SHARD_COUNT)]:
        config = LocalShardRunConfig(
            shard_count=SHARD_COUNT,
            first_shard=first,
            last_shard=last,
            command=[sys.executable, str(worker)],
            log_dir=tmp_path / f"pool-{first}",
            environment={"SHARD_TEST_OUTPUT": str(tmp_path)},
        )
        assert run_local_shards(config) == 0
        assert {path.name for path in config.log_dir.glob("*.log")} == {
            f"group-{shard}.log" for shard in range(first, last + 1)
        }
    assert {path.name for path in tmp_path.glob(f"*-of-{SHARD_COUNT}")} == {
        f"{shard}-of-{SHARD_COUNT}" for shard in range(1, SHARD_COUNT + 1)
    }


@pytest.mark.parametrize("first,last", [(0, 1), (2, 1), (1, SHARD_COUNT + 1), (SHARD_COUNT + 1, None)])
def test_runner_rejects_ranges_outside_the_global_plan(tmp_path: Path, first: int, last: int | None) -> None:
    with pytest.raises(ValidationError):
        LocalShardRunConfig(
            shard_count=SHARD_COUNT,
            first_shard=first,
            last_shard=last,
            command=[sys.executable, "-c", "pass"],
            log_dir=tmp_path,
        )


def test_cli_keeps_global_shard_ids_when_running_only_the_last_pool(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    worker = tmp_path / "worker.py"
    _write_worker(worker, fail_one=False)
    monkeypatch.setenv("SHARD_TEST_OUTPUT", str(tmp_path))
    assert (
        main(
            [
                "run-local",
                "--shards",
                str(SHARD_COUNT),
                "--first-shard",
                "2",
                "--last-shard",
                str(SHARD_COUNT),
                "--log-dir",
                str(tmp_path / "logs"),
                "--",
                sys.executable,
                str(worker),
            ]
        )
        == 0
    )
    assert not (tmp_path / f"1-of-{SHARD_COUNT}").exists()
    assert (tmp_path / f"2-of-{SHARD_COUNT}").exists()
    assert (tmp_path / f"{SHARD_COUNT}-of-{SHARD_COUNT}").exists()
