"""Exercise diagnostic tools through real commands and pytest processes."""

import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest


@pytest.mark.skipif(sys.platform != "linux", reason="Linux resource observation uses procfs and cgroups")
@pytest.mark.parametrize("enabled", ["false", "true"])
@pytest.mark.parametrize("status", [0, 7])
def test_resource_diagnostics_preserve_command_result(tmp_path: Path, enabled: str, status: int) -> None:
    result = subprocess.run(
        [sys.executable, "-m", "ci_esta.diagnostics", sys.executable, "-c",
         f"import sys; print('command survived'); sys.exit({status})"],
        cwd=tmp_path,
        env={**os.environ, "CI_TEST_RESOURCE_OBSERVABILITY": enabled,
             "CI_TEST_RESOURCE_OBSERVABILITY_INTERVAL_SECONDS": "1"},
        capture_output=True, text=True, timeout=15,
    )
    assert result.returncode == status, result.stdout + result.stderr
    assert "command survived" in result.stdout
    assert ("[ci-test-resource] runner capacity" in result.stdout) == (enabled == "true")
    if enabled == "true":
        assert f"command status={status}" in result.stdout


@pytest.mark.parametrize("fails", [False, True])
def test_watchdog_terminates_post_session_leak_with_original_status(tmp_path: Path, fails: bool) -> None:
    (tmp_path / "test_leak.py").write_text(
        "import threading, time\n"
        "def test_leak():\n"
        "    threading.Thread(target=lambda: time.sleep(60)).start()\n"
        f"    assert {not fails}\n", encoding="utf-8",
    )
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-p", "ci_esta.testing.pytest_watchdog", "-q", str(tmp_path)],
        cwd=tmp_path,
        env={**os.environ, "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1", "PYTEST_HANG_WATCHDOG_SECONDS": "1",
             "PYTEST_POST_SESSION_GRACE_SECONDS": "1"},
        capture_output=True, text=True, timeout=12,
    )
    assert result.returncode == int(fails), result.stdout + result.stderr
    assert "forcing exit" in result.stderr
    assert f"exitstatus={int(fails)}" in result.stderr


@pytest.mark.skipif(sys.platform != "linux", reason="Linux process lifecycle")
def test_resource_wrapper_forwards_termination_and_reaps_children(tmp_path: Path) -> None:
    ready = tmp_path / "ready"
    process = subprocess.Popen(
        [sys.executable, "-m", "ci_esta.diagnostics", sys.executable, "-c",
         "import os, pathlib, time; pathlib.Path('ready').write_text(str(os.getpid())); time.sleep(60)"],
        cwd=tmp_path, env={**os.environ, "CI_TEST_RESOURCE_OBSERVABILITY": "true"},
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, start_new_session=True,
    )
    try:
        deadline = time.monotonic() + 5
        while not ready.exists() and time.monotonic() < deadline:
            time.sleep(0.02)
        assert ready.exists()
        child = int(ready.read_text())
        process.terminate()
        output, errors = process.communicate(timeout=5)
        assert process.returncode in (-signal.SIGTERM, 128 + signal.SIGTERM), output + errors
        # The command group exits before its orphan is reaped by the runner's
        # init process. Give that independent reaper a bounded opportunity.
        deadline = time.monotonic() + 2
        while Path(f"/proc/{child}").exists() and time.monotonic() < deadline:
            time.sleep(0.02)
        with pytest.raises(ProcessLookupError):
            os.kill(child, 0)
    finally:
        # Reap the intentionally long-lived fixture even when the regression fails.
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait(timeout=5)


def test_watchdog_reports_mid_test_hang_without_forcing_success(tmp_path: Path) -> None:
    (tmp_path / "test_slow.py").write_text(
        "import time\ndef test_slow():\n    time.sleep(2.5)\n    assert False\n", encoding="utf-8",
    )
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-p", "ci_esta.testing.pytest_watchdog", "-q", "-s", str(tmp_path)],
        cwd=tmp_path,
        env={**os.environ, "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1", "PYTEST_HANG_WATCHDOG_SECONDS": "1"},
        capture_output=True, text=True, timeout=12,
    )
    assert result.returncode == 1, result.stdout + result.stderr
    assert "no pytest progress" in result.stderr
    assert "test_slow" in result.stderr
    assert "forcing exit" not in result.stderr


@pytest.mark.skipif(sys.platform != "linux", reason="Linux process lifecycle")
def test_resource_monitor_does_not_keep_output_pipes_open_after_command(tmp_path: Path) -> None:
    result = subprocess.run(
        [sys.executable, "-m", "ci_esta.diagnostics", sys.executable, "-c", "print('done')"],
        cwd=tmp_path, env={**os.environ, "CI_TEST_RESOURCE_OBSERVABILITY": "true",
                           "CI_TEST_RESOURCE_OBSERVABILITY_INTERVAL_SECONDS": "60"},
        capture_output=True, text=True, timeout=5,
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize("failure", ["session.exitstatus = 3", "raise RuntimeError('late hook failure')"])
def test_watchdog_preserves_late_session_failure(tmp_path: Path, failure: str) -> None:
    (tmp_path / "test_late.py").write_text("def test_ok(): pass\n", encoding="utf-8")
    (tmp_path / "conftest.py").write_text(
        "import pytest, threading, time\n"
        "@pytest.hookimpl(wrapper=True)\n"
        "def pytest_sessionfinish(session):\n"
        "    yield\n"
        "    threading.Thread(target=lambda: time.sleep(60)).start()\n"
        f"    {failure}\n", encoding="utf-8",
    )
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-p", "ci_esta.testing.pytest_watchdog", "-q", str(tmp_path)],
        cwd=tmp_path, env={**os.environ, "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
                           "PYTEST_HANG_WATCHDOG_SECONDS": "1", "PYTEST_POST_SESSION_GRACE_SECONDS": "1"},
        capture_output=True, text=True, timeout=12,
    )
    assert result.returncode == 3, result.stdout + result.stderr
    assert "forcing exit" in result.stderr
