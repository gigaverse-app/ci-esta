"""Compatibility exports; pytest-selective owns the implementation."""

import argparse as argparse
import ast as ast
import io as io
import os as os
import shutil as shutil
import subprocess as subprocess
import sys
import tempfile as tempfile
import tokenize as tokenize
from dataclasses import dataclass as dataclass
from dataclasses import replace as replace
from pathlib import Path as Path
from pathlib import PurePosixPath as PurePosixPath

import pytest_selective.pytest_expansion as _implementation
from pytest_selective.pytest_expansion import ACTIVATION as ACTIVATION
from pytest_selective.pytest_expansion import GIT_LOCATION_ENV as GIT_LOCATION_ENV
from pytest_selective.pytest_expansion import MARKER as MARKER
from pytest_selective.pytest_expansion import MODULE_DECLARATIONS as MODULE_DECLARATIONS
from pytest_selective.pytest_expansion import PYTHON_SOURCES as PYTHON_SOURCES
from pytest_selective.pytest_expansion import SCOPES as SCOPES
from pytest_selective.pytest_expansion import Declaration as Declaration
from pytest_selective.pytest_expansion import DeclarationKey as DeclarationKey
from pytest_selective.pytest_expansion import Expansion as Expansion
from pytest_selective.pytest_expansion import LocatedDeclaration as LocatedDeclaration
from pytest_selective.pytest_expansion import Renames as Renames
from pytest_selective.pytest_expansion import SourceTree as SourceTree
from pytest_selective.pytest_expansion import Surface as Surface
from pytest_selective.pytest_expansion import check as check
from pytest_selective.pytest_expansion import expansions as expansions
from pytest_selective.pytest_expansion import git as git
from pytest_selective.pytest_expansion import git_environment as git_environment
from pytest_selective.pytest_expansion import inspect_source as inspect_source
from pytest_selective.pytest_expansion import main as main
from pytest_selective.pytest_expansion import module_nodes as module_nodes
from pytest_selective.pytest_expansion import moved_packages as moved_packages
from pytest_selective.pytest_expansion import protected as protected
from pytest_selective.pytest_expansion import reason_before as reason_before
from pytest_selective.pytest_expansion import surfaces as surfaces
from pytest_selective.pytest_expansion import within as within
from pytest_selective.pytest_expansion import worktree_snapshot as worktree_snapshot

if __name__ == "__main__":
    raise SystemExit(_implementation.main())

sys.modules[__name__] = _implementation
