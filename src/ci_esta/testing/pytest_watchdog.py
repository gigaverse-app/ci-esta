"""Opt-in pytest progress diagnostics, including bounded post-session thread leaks.

Load with ``-p ci_esta.testing.pytest_watchdog``. PYTEST_HANG_WATCHDOG_SECONDS
enables progress dumps; zero disables the plugin. PYTEST_POST_SESSION_GRACE_SECONDS
retains the consumer's post-session grace (15 seconds by default). Forced exit is
restricted to a finished session and reads its current exit status at that point.
The plugin is intended for a standalone CI pytest process, not embedded pytest.
"""

import faulthandler
import os
import sys
import threading
import time

import pytest


class ProgressWatchdog:
    """One pytest invocation owns its progress deadline and diagnostic thread."""

    def __init__(self, timeout_seconds: int, post_session_grace_seconds: int) -> None:
        self.timeout_seconds = timeout_seconds
        self.post_session_grace_seconds = post_session_grace_seconds
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._deadline = 0.0
        self._phase = "pytest startup"
        self._session: pytest.Session | None = None
        self._thread = threading.Thread(target=self._run, name="pytest-hang-watchdog", daemon=True)

    def start(self) -> None:
        faulthandler.enable(file=sys.stderr, all_threads=True)
        self._reset("pytest configured")
        self._thread.start()

    def _reset(self, phase: str) -> None:
        with self._lock:
            self._phase = phase
            self._deadline = time.monotonic() + self.timeout_seconds

    def pytest_runtest_logstart(self, nodeid: str) -> None:
        self._reset(f"started {nodeid}")

    def pytest_runtest_logfinish(self, nodeid: str) -> None:
        self._reset(f"finished {nodeid}")

    @pytest.hookimpl(trylast=True)
    def pytest_sessionfinish(self, session: pytest.Session) -> None:
        with self._lock:
            self._session = session
            self._phase = f"pytest_sessionfinish exitstatus={int(session.exitstatus)}"
            self._deadline = time.monotonic() + self.post_session_grace_seconds

    def pytest_unconfigure(self) -> None:
        # Configuration failures have no finished session to protect. A finished
        # standalone session keeps its daemon watchdog through interpreter shutdown,
        # where a leaked non-daemon thread would otherwise hold the process forever.
        if self._session is None:
            self._stop.set()
            self._thread.join(timeout=1)

    def _run(self) -> None:
        while not self._stop.wait(0.25):
            with self._lock:
                if time.monotonic() < self._deadline:
                    continue
                phase = self._phase
                session = self._session
                self._deadline = time.monotonic() + self.timeout_seconds
            print(
                f"\n[pytest-hang-watchdog] no pytest progress for {self.timeout_seconds}s; last phase: {phase}",
                file=sys.stderr, flush=True,
            )
            print("[pytest-hang-watchdog] live threads:", file=sys.stderr, flush=True)
            for thread in threading.enumerate():
                print(
                    f"[pytest-hang-watchdog] name={thread.name!r} ident={thread.ident} daemon={thread.daemon}",
                    file=sys.stderr, flush=True,
                )
            faulthandler.dump_traceback(file=sys.stderr, all_threads=True)
            if session is not None:
                # Never manufacture a green result: late hooks may have changed
                # session.exitstatus since sessionfinish first ran.
                status = int(session.exitstatus)
                print(
                    f"[pytest-hang-watchdog] session already finished with exitstatus={status}; "
                    "forcing exit to avoid a shutdown hang on a leaked non-daemon thread.",
                    file=sys.stderr, flush=True,
                )
                sys.stderr.flush()
                sys.stdout.flush()
                os._exit(status)


def pytest_configure(config: pytest.Config) -> None:
    try:
        timeout = int(os.environ.get("PYTEST_HANG_WATCHDOG_SECONDS", "0"))
        grace = int(os.environ.get("PYTEST_POST_SESSION_GRACE_SECONDS", "15"))
    except ValueError as exc:
        raise pytest.UsageError("watchdog timeout and post-session grace must be integer seconds") from exc
    if timeout <= 0:
        return
    if grace < 0:
        raise pytest.UsageError("post-session grace must be nonnegative")
    watchdog = ProgressWatchdog(timeout, grace)
    config.pluginmanager.register(watchdog, "ci-esta-progress-watchdog")
    watchdog.start()
