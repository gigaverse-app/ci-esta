"""
Opt-in pytest plugin proving exhaustive execution, not merely a JUnit file.

Load with ``-p ci_esta.testing.pytest_completion --completion-receipt=PATH``.
Consumers verify every shard receipt and report before publishing a completion step.

``--completion-accept-all-deselected`` lets a lane's own filter empty a shard: a planner that
packs whole files by duration can give one shard only files the lane's ``-m``/``-k`` expression
deselects, and pytest reports that as exit 5. With the option, a fully executed session that
collected at least one item and deselected every one exits 0 instead. A session that collected
nothing still exits 5, so an empty or wrong manifest keeps failing.
"""

from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

import pytest

_EXECUTION_COMPLETED = pytest.StashKey[bool]()
_DESELECTED = pytest.StashKey[int]()


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption("--completion-receipt", default=None, help="Write raw exit status only after exhaustive execution")
    parser.addoption(
        "--completion-accept-all-deselected",
        action="store_true",
        default=False,
        help="Exit 0, not 5, when tests were collected and the lane's filters deselected every one",
    )


def pytest_sessionstart(session: pytest.Session) -> None:
    session.config.stash[_EXECUTION_COMPLETED] = False
    session.config.stash[_DESELECTED] = 0
    receipt = session.config.getoption("completion_receipt")
    if receipt:
        Path(receipt).unlink(missing_ok=True)


@pytest.hookimpl(wrapper=True, tryfirst=True)
def pytest_runtestloop(session: pytest.Session) -> Generator[None, bool | None, bool | None]:
    # Only normal return from the entire execution hook proves completion.
    # pytest.exit can request 0/1/5 without setting shouldstop or shouldfail;
    # its exception must propagate past this yield without issuing proof.
    result = yield
    session.config.stash[_EXECUTION_COMPLETED] = not session.config.option.collectonly
    return result


def pytest_deselected(items: list[pytest.Item]) -> None:
    # Every built-in and plugin deselection (-m, -k, --deselect) reports here.
    if items:
        config = items[0].config
        config.stash[_DESELECTED] = config.stash.get(_DESELECTED, 0) + len(items)


@pytest.hookimpl(trylast=True)
def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    receipt = session.config.getoption("completion_receipt")
    completed = session.config.stash.get(_EXECUTION_COMPLETED, False)
    if (
        session.config.getoption("completion_accept_all_deselected")
        and completed
        and exitstatus == pytest.ExitCode.NO_TESTS_COLLECTED
        and session.testscollected == 0
        and session.config.stash.get(_DESELECTED, 0) > 0
    ):
        # pytest returns session.exitstatus after this hook, so the shard command and receipt agree.
        session.exitstatus = pytest.ExitCode.OK
        exitstatus = int(pytest.ExitCode.OK)
    # Exit 1 alone also describes --maxfail/-x. Those sessions leave unexecuted
    # tests, so their valid-looking JUnit must NEVER authorize incremental reuse.
    if receipt and completed and not session.shouldfail and not session.shouldstop and exitstatus in {0, 1, 5}:
        Path(receipt).write_text(f"{exitstatus}\n")
