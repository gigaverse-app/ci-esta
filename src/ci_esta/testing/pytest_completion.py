"""
Opt-in pytest plugin proving exhaustive execution, not merely a JUnit file.

Load with ``-p ci_esta.testing.pytest_completion --completion-receipt=PATH``.
Consumers verify every shard receipt and report before publishing a completion step.
"""

from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

import pytest

_EXECUTION_COMPLETED = pytest.StashKey[bool]()


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption("--completion-receipt", default=None, help="Write raw exit status only after exhaustive execution")


def pytest_sessionstart(session: pytest.Session) -> None:
    session.config.stash[_EXECUTION_COMPLETED] = False
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


@pytest.hookimpl(trylast=True)
def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    receipt = session.config.getoption("completion_receipt")
    # Exit 1 alone also describes --maxfail/-x. Those sessions leave unexecuted
    # tests, so their valid-looking JUnit must NEVER authorize incremental reuse.
    if (
        receipt
        and session.config.stash.get(_EXECUTION_COMPLETED, False)
        and not session.shouldfail
        and not session.shouldstop
        and exitstatus in {0, 1, 5}
    ):
        Path(receipt).write_text(f"{exitstatus}\n")
