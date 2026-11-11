"""Attach execution identity to JUnit at its producer, including xdist's controller.

No network calls or local-run changes. Report consumers can distinguish freshly
executed XML from reports retained by an earlier workflow attempt.
"""

from __future__ import annotations

import os
from collections.abc import Generator
from pathlib import Path
from xml.etree.ElementTree import Element, SubElement, tostring

import pytest

try:
    from xdist import is_xdist_worker
except ImportError:
    is_xdist_worker = None

from ci_esta.measurements import MeasurementIdentity
from ci_esta.testing.junit import EXECUTION_PROPERTY, _parse_junit
from ci_esta.testing.persistence import write_atomic_text

IDENTITY = pytest.StashKey[MeasurementIdentity]()


def pytest_configure(config: pytest.Config) -> None:
    if os.environ.get("GITHUB_ACTIONS") != "true":
        return
    try:
        config.stash[IDENTITY] = MeasurementIdentity.from_environment(required=True)
    except (ValueError, OSError):
        # Optional scheduling evidence must not change test outcomes.
        return


@pytest.hookimpl(wrapper=True, tryfirst=True)
def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> Generator[None, None, None]:
    # Enclose the JUnit plugin's writer, then annotate only a successful session.
    yield
    # Child pytest controllers can inherit a parent's worker environment. Use
    # xdist's session identity, not those inherited environment variables.
    if is_xdist_worker is not None and is_xdist_worker(session):
        return
    identity = session.config.stash.get(IDENTITY, None)
    destination = session.config.getoption("xmlpath", default=None)
    if identity is None or not destination or exitstatus != 0:
        return
    path = Path(destination)
    root = _parse_junit(path)
    if root is None:
        return
    for suite in root.iter("testsuite"):
        properties = suite.find("properties")
        if properties is None:
            properties = Element("properties")
            suite.insert(0, properties)
        for prop in list(properties):
            if prop.get("name") == EXECUTION_PROPERTY:
                properties.remove(prop)
        SubElement(properties, "property", name=EXECUTION_PROPERTY, value=identity.model_dump_json())
    try:
        write_atomic_text(tostring(root, encoding="unicode"), path)
    except OSError:
        return
