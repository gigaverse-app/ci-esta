"""Compatibility exports; pytest-selective owns the implementation."""

import ast as ast
import sys
from functools import cache as cache
from pathlib import Path as Path

import pytest_selective.hygiene as _implementation
from pydantic import BaseModel as BaseModel
from pydantic import ConfigDict as ConfigDict
from pytest_selective.ast_imports import import_candidates as import_candidates
from pytest_selective.ast_imports import iter_imports as iter_imports
from pytest_selective.ast_imports import module_file as module_file
from pytest_selective.hygiene import TestImportViolation as TestImportViolation
from pytest_selective.hygiene import assert_test_file_isolation as assert_test_file_isolation
from pytest_selective.hygiene import discover_test_modules as discover_test_modules
from pytest_selective.hygiene import find_test_import_violations as find_test_import_violations
from pytest_selective.hygiene import is_test_module as is_test_module
from pytest_selective.test_inventory import TEST_FILE_PATTERNS as TEST_FILE_PATTERNS
from pytest_selective.test_inventory import is_test_module_name as is_test_module_name

sys.modules[__name__] = _implementation
