"""A real pytest process must finish its selected work before issuing evidence."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def run_pytest(directory: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-p",
            "ci_esta.testing.pytest_completion",
            "--completion-receipt=receipt",
            "--junitxml=junit-group-1.xml",
            "-o",
            "junit_family=legacy",
            "-q",
            *args,
        ],
        cwd=directory,
        env={
            **os.environ,
            "PYTHONPATH": str(ROOT / "src"),
            "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
            "PYTEST_ADDOPTS": "",
        },
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )


@pytest.mark.parametrize("maxfail", [0, 2])
@pytest.mark.parametrize("fails", [False, True])
def test_completion_receipt_requires_exhaustive_execution(tmp_path: Path, maxfail: int, fails: bool) -> None:
    (tmp_path / "test_probe.py").write_text(
        f"import pytest\n@pytest.mark.parametrize('case', range(3))\ndef test_probe(case): assert {not fails!r}\n"
    )
    receipt = tmp_path / "receipt"
    receipt.write_text("0\n")  # A rerun must never inherit an earlier receipt.
    result = run_pytest(tmp_path, f"--maxfail={maxfail}")
    assert result.returncode == (1 if fails else 0), result.stderr
    assert (tmp_path / "junit-group-1.xml").is_file()
    if fails and maxfail:
        assert not receipt.exists(), "Fail-fast JUnit is not completed evidence"
    else:
        assert receipt.read_text().strip() == str(result.returncode)


@pytest.mark.parametrize("source", ["raise RuntimeError('collection')", "def test_stop(): raise KeyboardInterrupt()"])
def test_abnormal_exit_cannot_issue_a_completion_receipt(tmp_path: Path, source: str) -> None:
    (tmp_path / "test_probe.py").write_text(source)
    result = run_pytest(tmp_path)
    assert result.returncode == 2, result.stderr
    assert not (tmp_path / "receipt").exists()


@pytest.mark.parametrize("exitcode", [0, 1, 2, 5])
@pytest.mark.parametrize("phase", ["collection", "setup", "call", "teardown"])
def test_explicit_abort_cannot_certify_unexecuted_tests(tmp_path: Path, exitcode: int, phase: str) -> None:
    """Even a success-looking exit must not authorize reuse of an unfinished shard."""
    abort = f"pytest.exit('abort requested', returncode={exitcode})"
    sources = {
        "collection": "def test_b(): pass",
        "setup": f"@pytest.fixture(autouse=True)\ndef stop(): {abort}\ndef test_b(): pass",
        "call": f"def test_b(): {abort}",
        "teardown": f"@pytest.fixture(autouse=True)\ndef stop():\n yield\n {abort}\ndef test_b(): pass",
    }
    (tmp_path / "test_a.py").write_text("def test_a(): assert False\n")
    (tmp_path / "test_b.py").write_text("import pytest\n" + sources[phase] + "\n")
    if phase == "collection":
        (tmp_path / "conftest.py").write_text(f"import pytest\ndef pytest_collection_modifyitems(items): {abort}\n")
    (tmp_path / "test_c.py").write_text(
        "from pathlib import Path\ndef test_c():\n Path('finished').touch()\n assert False\n"
    )
    receipt = tmp_path / "receipt"
    receipt.write_text("0\n")
    result = run_pytest(tmp_path, "--maxfail=0")
    assert result.returncode == exitcode, result.stdout + result.stderr
    assert not (tmp_path / "finished").exists()
    assert not receipt.exists(), "An aborted session must invalidate its old receipt and issue no new proof"


@pytest.mark.parametrize("mode", ["empty", "deselected", "skipped", "collect-only"])
def test_completion_distinguishes_execution_from_collection(tmp_path: Path, mode: str) -> None:
    sources = {
        "empty": "",
        "deselected": "def test_one(): pass\n",
        "skipped": "import pytest\n@pytest.mark.skip\ndef test_one(): pass\n",
        "collect-only": "def test_one(): assert False\n",
    }
    (tmp_path / "test_probe.py").write_text(sources[mode])
    args = {"deselected": ["-k", "not test_one"], "collect-only": ["--collect-only"]}.get(mode, [])
    result = run_pytest(tmp_path, *args)
    assert result.returncode == (5 if mode in {"empty", "deselected"} else 0), result.stderr
    receipt = tmp_path / "receipt"
    if mode == "collect-only":
        assert not receipt.exists(), "Collection alone never proves execution"
    else:
        assert receipt.read_text().strip() == str(result.returncode)


LANE_MARKER = "not other_lane"
OTHER_LANE_ONLY = "import pytest\npytestmark = pytest.mark.other_lane\n" + "".join(
    f"def test_{case}(): pass\n" for case in range(3)
)


def write_shard_worker(directory: Path, *extra_args: str) -> Path:
    """A shard command shaped like an adopter's: one pytest run over its manifest, with a lane marker."""
    worker = directory / "shard.py"
    worker.write_text(
        "\n".join(
            (
                "import os, subprocess, sys",
                'shard = os.environ["GV_PYTEST_SHARD_INDEX"]',
                'paths = [line for line in open(f"group-{shard}.txt").read().splitlines() if line]',
                "raise SystemExit(subprocess.call([sys.executable, '-m', 'pytest', '-p', 'ci_esta.testing.pytest_completion',",
                "    f'--completion-receipt=pytest-status-group-{shard}', f'--junitxml=junit-group-{shard}.xml',",
                f"    '-o', 'markers=other_lane', '-m', {LANE_MARKER!r}, '-q', *{list(extra_args)!r}, *paths]))",
            )
        )
        + "\n"
    )
    return worker


def run_local(directory: Path, worker: Path, shards: int) -> int:
    from ci_esta.testing.local_shards import LocalShardRunConfig, run_local_shards

    return run_local_shards(
        LocalShardRunConfig(
            shard_count=shards,
            command=[sys.executable, str(worker)],
            log_dir=directory / "logs",
            environment={"PYTHONPATH": str(ROOT / "src"), "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1", "PYTEST_ADDOPTS": ""},
        )
    )


def test_shard_holding_only_lane_deselected_files_completes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """REGRESSION: duration packing can give one shard only files the lane marker deselects.

    gigaverse-backend run 42418197930 packed a real-Celery-worker file alone into shard 1 of 12:
    "collected 11 items / 11 deselected / 0 selected", pytest exit 5, and run-local failed the job
    although every test the lane owns passed. The verifier already accepted that receipt.
    """
    monkeypatch.chdir(tmp_path)
    (tmp_path / "test_other_lane.py").write_text(OTHER_LANE_ONLY)
    (tmp_path / "test_unit.py").write_text("def test_unit(): pass\n")
    (tmp_path / "group-1.txt").write_text("test_other_lane.py\n")
    (tmp_path / "group-2.txt").write_text("test_unit.py\n")

    assert run_local(tmp_path, write_shard_worker(tmp_path), shards=2) == 1, "pytest's raw exit 5 fails the shard"
    assert run_local(tmp_path, write_shard_worker(tmp_path, "--completion-accept-all-deselected"), shards=2) == 0
    for shard in (1, 2):
        assert (tmp_path / f"pytest-status-group-{shard}").read_text().strip() == "0"
        assert (tmp_path / f"junit-group-{shard}.xml").stat().st_size


@pytest.mark.parametrize(
    "mode", ["empty-file", "no-test-files", "partly-deselected-failure", "collect-only", "fail-fast"]
)
def test_accepting_all_deselected_never_hides_missing_or_failed_work(tmp_path: Path, mode: str) -> None:
    """Only a session that collected tests and deselected every one becomes a pass; nothing else changes."""
    sources = {
        "empty-file": {"test_probe.py": ""},
        "no-test-files": {"helper.py": "def test_not_collected(): pass\n"},
        "partly-deselected-failure": {
            "test_other_lane.py": OTHER_LANE_ONLY,
            "test_probe.py": "def test_x(): assert False\n",
        },
        "collect-only": {"test_other_lane.py": OTHER_LANE_ONLY},
        "fail-fast": {
            "test_other_lane.py": OTHER_LANE_ONLY,
            "test_probe.py": "def test_x(): assert False\ndef test_y(): pass\n",
        },
    }[mode]
    for name, source in sources.items():
        (tmp_path / name).write_text(source)
    args = {"collect-only": ["--collect-only"], "fail-fast": ["--maxfail=1"]}.get(mode, [])
    result = run_pytest(
        tmp_path, "--completion-accept-all-deselected", "-o", "markers=other_lane", "-m", LANE_MARKER, *args
    )
    expected = {"empty-file": 5, "no-test-files": 5, "partly-deselected-failure": 1, "collect-only": 5, "fail-fast": 1}
    assert result.returncode == expected[mode], result.stdout + result.stderr
    receipt = tmp_path / "receipt"
    if mode in {"collect-only", "fail-fast"}:
        assert not receipt.exists(), "Collection or fail-fast never proves execution"
    else:
        assert receipt.read_text().strip() == str(expected[mode])
