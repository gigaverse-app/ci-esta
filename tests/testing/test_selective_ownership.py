"""Compatibility names share one canonical pytest-selective implementation."""

import importlib

import pytest


@pytest.mark.parametrize("name", ["hygiene", "pytest_expansion"])
def test_pytest_guards_are_owned_by_the_selector(name: str) -> None:
    assert importlib.import_module(f"ci_esta.testing.{name}") is importlib.import_module(f"pytest_selective.{name}")
