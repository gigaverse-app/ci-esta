"""
Enforce recursive, path-shaped import boundaries in Python repositories.

The boundary exists at every declared source/test tree, not merely at a service root.  A production module may import
modules inside its tree and below it, and may import an explicitly shared ``common`` root.  A module inside a deeper
paired tree may not reach upward to an ancestor tree or sideways into a cousin tree.  Parent trees may import child
trees; that direction is why a changed child can require ancestor tests.

Tests use the same recursive shape through an explicit test/source pairing. For example,
``tests/test_service/test_area`` pairs with ``src/package/service/area``.  Code in that test directory may import only
the paired source directory or descendants, local test support beside/below it, and explicit common roots.

These rules are intentionally structural.  They make a path-scoped test plan depend on a checked invariant instead of an
informal belief that sibling trees probably do not affect one another.

One scan treats the filesystem as static: every layout root is resolved once, and every dotted module name, root
containment question, and paired-directory existence check is answered once and memoized for the rest of that scan.
The memo lives only as long as one ``find_recursive_import_violations`` call, so separate calls never share answers.
"""

from __future__ import annotations

import ast
from collections.abc import Iterable
from pathlib import Path

from pydantic import BaseModel, ConfigDict
from pytest_selective.ast_imports import iter_imports, parse_ast


class ImportBoundaryLayout(BaseModel):
    """
    Consumer-owned filesystem layout for the recursive boundary check.
    """

    model_config = ConfigDict(frozen=True)

    source_roots: tuple[Path, ...]
    tests_root: Path
    test_source_mappings: dict[Path, Path]
    common_roots: tuple[Path, ...] = ()
    module_search_roots: tuple[Path, ...] = (Path("src"), Path("."))
    test_directory_prefix: str = "test_"


class RecursiveImportViolation(BaseModel):
    """
    One import whose resolved local target crosses a recursive boundary.
    """

    model_config = ConfigDict(frozen=True)

    importer: Path
    line: int
    reason: str
    target: Path | None = None

    def __str__(self) -> str:
        target = f" -> {self.target.as_posix()}" if self.target is not None else ""
        return f"{self.importer.as_posix()}:{self.line}: {self.reason}{target}"


def _is_within(path: Path, root: Path) -> bool:
    return path == root or path.is_relative_to(root)


def _absolute(repo_root: Path, path: Path) -> Path:
    return (repo_root / path).resolve()


def _module_file(base: Path) -> Path | None:
    module = base.with_suffix(".py")
    if module.is_file():
        return module.resolve()
    package = base / "__init__.py"
    if package.is_file():
        return package.resolve()
    return None


class _ScanFilesystem:
    """
    Memoized filesystem probes for one scan over a tree assumed static while it runs.

    A large repository names the same modules from thousands of import statements.  Probing and canonicalizing each
    dotted name once, instead of once per statement, removes almost all of the scan's ``stat``/``lstat`` work.  Most
    remaining names are third-party or standard-library modules that are absent from every search root; a memoized
    directory check answers those without probing for files.  Create one instance per scan and never share it:
    another scan may target a different repository or a changed tree.
    """

    def __init__(self, search_roots: tuple[Path, ...]) -> None:
        self._search_roots = search_roots
        self._modules: dict[str, Path | None] = {}
        self._directories: dict[Path, bool] = {}
        self._file_or_dir: dict[Path, bool] = {}

    def module(self, dotted: str) -> Path | None:
        if dotted not in self._modules:
            self._modules[dotted] = self._find_module(dotted)
        return self._modules[dotted]

    def _find_module(self, dotted: str) -> Path | None:
        for search_root in self._search_roots:
            base = search_root.joinpath(*dotted.split("."))
            # Both candidate files (``base.py`` and ``base/__init__.py``) live
            # below ``base.parent``, so neither exists unless it is a directory.
            if not self._is_directory(base.parent, search_root):
                continue
            resolved = _module_file(base)
            if resolved is not None:
                return resolved
        return None

    def _is_directory(self, path: Path, search_root: Path) -> bool:
        # A path is a directory only if its parent is one, so checking the
        # parent first lets one missing top-level package answer every deeper
        # name below it.  The memoized value is always ``path.is_dir()``.
        if path not in self._directories:
            parent_is_directory = (
                path == search_root
                or not path.is_relative_to(search_root)
                or self._is_directory(path.parent, search_root)
            )
            self._directories[path] = parent_is_directory and path.is_dir()
        return self._directories[path]

    def is_file_or_dir(self, path: Path) -> bool:
        if path not in self._file_or_dir:
            self._file_or_dir[path] = path.is_file() or path.is_dir()
        return self._file_or_dir[path]


class _RootLookup:
    """
    Find the deepest root in one fixed set that contains a path, memoized per path for one scan.

    Every root containing ``path`` is ``path`` itself or one of its parents, and those all have distinct depths, so the
    first ancestor that is a root is the longest match.  That equals picking the longest root ``r`` with
    ``path == r or path.is_relative_to(r)`` without comparing the path against every root.
    """

    def __init__(self, roots: Iterable[Path]) -> None:
        self._roots = frozenset(roots)
        self._containing: dict[Path, Path | None] = {}

    def containing(self, path: Path) -> Path | None:
        if path not in self._containing:
            self._containing[path] = next(
                (candidate for candidate in (path, *path.parents) if candidate in self._roots),
                None,
            )
        return self._containing[path]


def _importer_package(search_roots: tuple[Path, ...], importer: Path) -> str:
    # Longest roots win so ``src`` is preferred over ``.`` for production
    # modules when both technically contain the file.
    candidates: list[tuple[int, Path]] = []
    for search_root in search_roots:
        if importer.is_relative_to(search_root):
            candidates.append((len(search_root.parts), search_root))
    if not candidates:
        return ""
    search_root = max(candidates, key=lambda candidate: candidate[0])[1]
    return ".".join(importer.relative_to(search_root).parent.parts)


def _from_base(node: ast.ImportFrom, importer_package: str) -> str:
    if not node.level:
        return node.module or ""
    package_parts = importer_package.split(".") if importer_package else []
    if node.level - 1 > len(package_parts):
        return ""
    prefix = package_parts[: len(package_parts) - (node.level - 1)]
    if node.module:
        prefix.extend(node.module.split("."))
    return ".".join(prefix)


def _resolved_import_targets(
    filesystem: _ScanFilesystem,
    importer_package: str,
    node: ast.Import | ast.ImportFrom,
) -> set[Path]:
    """
    Resolve only real local modules loaded by one import statement.

    ``from package import child`` is ambiguous in Python: ``child`` may be an attribute or a submodule.  When a real
    child module exists, it is the structural dependency and the package ``__init__`` is not reported as a false upward
    import.  Otherwise the package module owns the attribute and is the dependency.
    """
    if isinstance(node, ast.Import):
        return {target for alias in node.names if (target := filesystem.module(alias.name)) is not None}

    base = _from_base(node, importer_package)
    base_target = filesystem.module(base) if base else None
    targets: set[Path] = set()
    for alias in node.names:
        if alias.name == "*":
            if base_target is not None:
                targets.add(base_target)
            continue
        child = f"{base}.{alias.name}" if base else alias.name
        child_target = filesystem.module(child)
        if child_target is not None:
            targets.add(child_target)
        elif base_target is not None:
            targets.add(base_target)
    return targets


def _python_files(root: Path) -> list[Path]:
    """
    Return Python files owned by a source root, including module roots.
    """
    if root.is_file():
        return [root] if root.suffix == ".py" else []
    if root.is_dir():
        return list(root.rglob("*.py"))
    return []


def _scoped_common_roots(roots: tuple[Path, ...]) -> tuple[Path, ...]:
    """
    Find convention-based ``common`` directories below owned trees.

    A nested ``<tree>/common`` is shared only inside ``<tree>``. Global
    common roots remain explicit because their scope can span otherwise
    unrelated source and test trees.
    """
    discovered: set[Path] = set()
    for root in roots:
        if not root.is_dir():
            continue
        if root.name == "common":
            discovered.add(root)
        discovered.update(candidate for candidate in root.rglob("common") if candidate.is_dir())
    return tuple(sorted(discovered, key=lambda path: (len(path.parts), str(path))))


def _allowed_common_target(
    importer: Path,
    target: Path,
    global_common_roots: _RootLookup,
    scoped_common_roots: _RootLookup,
) -> Path | None:
    global_common = global_common_roots.containing(target)
    if global_common is not None:
        return global_common
    scoped_common = scoped_common_roots.containing(target)
    if scoped_common is not None and _is_within(importer, scoped_common.parent):
        return scoped_common
    return None


def _test_mapping(
    test_file: Path,
    mappings: dict[Path, Path],
) -> tuple[Path, Path] | None:
    # Same deepest-ancestor argument as ``_RootLookup``: the first ancestor
    # that is a mapped test root is the longest containing one.
    for candidate in (test_file, *test_file.parents):
        source_root = mappings.get(candidate)
        if source_root is not None:
            return candidate, source_root
    return None


def _paired_source_directory(
    test_file: Path,
    test_root: Path,
    source_root: Path,
    test_directory_prefix: str,
) -> Path:
    relative_directory = test_file.parent.relative_to(test_root)
    # Only ``test_<name>`` directories declare another source boundary. Plain
    # directories such as ``integration`` or ``fixtures`` organize tests
    # inside the current boundary without claiming a sibling production tree.
    source_parts = [
        part.removeprefix(test_directory_prefix)
        for part in relative_directory.parts
        if part.startswith(test_directory_prefix)
    ]
    return source_root.joinpath(*source_parts)


def _relative(repo_root: Path, path: Path) -> Path:
    return path.relative_to(repo_root)


def _source_import_violation(
    importer: Path,
    target: Path,
    source_roots: _RootLookup,
    isolation_roots: _RootLookup,
    tests_root: Path,
    common_roots: _RootLookup,
    scoped_common_roots: _RootLookup,
    any_common_roots: _RootLookup,
) -> str | None:
    importer_common = any_common_roots.containing(importer)
    target_common = _allowed_common_target(importer, target, common_roots, scoped_common_roots)
    if target_common is not None:
        return None
    if scoped_common_roots.containing(target) is not None:
        return "source import must point to a sibling or descendant"
    if _is_within(target, tests_root):
        return "source files must not import tests"
    if source_roots.containing(target) is None:
        return None
    if importer_common is not None:
        return "common source must not depend on an isolated source tree"
    importer_boundary = isolation_roots.containing(importer)
    if importer_boundary is not None and _is_within(target, importer_boundary):
        return None
    return "source import must point to a sibling or descendant"


def _test_import_violation(
    importer: Path,
    target: Path,
    paired_source: Path,
    source_roots: _RootLookup,
    tests_root: Path,
    common_roots: _RootLookup,
    scoped_common_roots: _RootLookup,
) -> str | None:
    if _allowed_common_target(importer, target, common_roots, scoped_common_roots) is not None:
        return None
    if scoped_common_roots.containing(target) is not None:
        return "test support import must point to a sibling or descendant"
    if source_roots.containing(target) is not None:
        if target == paired_source or _is_within(target.parent, paired_source):
            return None
        return "test import must stay in its sibling source subtree"
    if _is_within(target, tests_root):
        # Pytest applies a parent conftest to its entire descendant tree. An
        # explicit import of the same support follows that built-in scope.
        if target.name == "conftest.py" and _is_within(importer, target.parent):
            return None
        if _is_within(target.parent, importer.parent):
            return None
        return "test support import must point to a sibling or descendant"
    return None


def find_recursive_import_violations(
    repo_root: Path,
    layout: ImportBoundaryLayout,
) -> list[RecursiveImportViolation]:
    """
    Return every statically resolvable local import-boundary violation.
    """
    repo_root = repo_root.resolve()
    search_roots = tuple(_absolute(repo_root, root) for root in layout.module_search_roots)
    source_roots = tuple(_absolute(repo_root, root) for root in layout.source_roots)
    tests_root = _absolute(repo_root, layout.tests_root)
    common_roots = tuple(_absolute(repo_root, root) for root in layout.common_roots)
    mappings = {
        _absolute(repo_root, test_root): _absolute(repo_root, source_root)
        for test_root, source_root in layout.test_source_mappings.items()
    }
    source_common_roots = _scoped_common_roots(source_roots)
    test_common_roots = _scoped_common_roots((tests_root,))
    filesystem = _ScanFilesystem(search_roots)
    test_files = sorted(path.resolve() for path in tests_root.rglob("*.py"))
    # Every explicit mapping is an isolation root.  Each deeper test directory
    # with a real sibling source directory declares another nested root.  This
    # is what makes the same rule work at arbitrary depth without pretending
    # organizational-only test folders are source boundaries.
    isolation_roots = set(mappings.values())
    isolation_roots.update(source_roots)
    for test_file in test_files:
        mapping = _test_mapping(test_file, mappings)
        if mapping is None:
            continue
        test_root, source_root = mapping
        relative_directory = test_file.parent.relative_to(test_root)
        for depth in range(len(relative_directory.parts) + 1):
            partial_test_file = test_root.joinpath(*relative_directory.parts[:depth], "placeholder.py")
            paired = _paired_source_directory(
                partial_test_file,
                test_root,
                source_root,
                layout.test_directory_prefix,
            )
            if filesystem.is_file_or_dir(paired):
                isolation_roots.add(paired)
    source_root_lookup = _RootLookup(source_roots)
    isolation_root_lookup = _RootLookup(isolation_roots)
    common_root_lookup = _RootLookup(common_roots)
    source_common_lookup = _RootLookup(source_common_roots)
    test_common_lookup = _RootLookup(test_common_roots)
    any_source_common_lookup = _RootLookup((*common_roots, *source_common_roots))
    violations: list[RecursiveImportViolation] = []

    source_files = sorted({path.resolve() for root in source_roots for path in _python_files(root)})
    for importer in source_files:
        importer_package = _importer_package(search_roots, importer)
        tree = parse_ast(importer.read_bytes(), filename=str(importer))
        for node in iter_imports(tree):
            for target in sorted(_resolved_import_targets(filesystem, importer_package, node)):
                reason = _source_import_violation(
                    importer,
                    target,
                    source_root_lookup,
                    isolation_root_lookup,
                    tests_root,
                    common_root_lookup,
                    source_common_lookup,
                    any_source_common_lookup,
                )
                if reason is not None:
                    violations.append(
                        RecursiveImportViolation(
                            importer=_relative(repo_root, importer),
                            line=node.lineno,
                            reason=reason,
                            target=_relative(repo_root, target),
                        )
                    )

    for importer in test_files:
        if common_root_lookup.containing(importer) is not None:
            continue
        mapping = _test_mapping(importer, mappings)
        if mapping is None:
            # Package markers contain no tests and declare no ownership. They
            # may sit in organizational parents above several mapped trees.
            if importer.name == "__init__.py":
                continue
            violations.append(
                RecursiveImportViolation(
                    importer=_relative(repo_root, importer),
                    line=1,
                    reason="is outside every test/source mapping and common root",
                )
            )
            continue
        test_root, source_root = mapping
        paired_source = _paired_source_directory(
            importer,
            test_root,
            source_root,
            layout.test_directory_prefix,
        )
        if not filesystem.is_file_or_dir(paired_source):
            violations.append(
                RecursiveImportViolation(
                    importer=_relative(repo_root, importer),
                    line=1,
                    reason=f"has no sibling source directory {_relative(repo_root, paired_source).as_posix()}",
                )
            )
            continue
        importer_package = _importer_package(search_roots, importer)
        tree = parse_ast(importer.read_bytes(), filename=str(importer))
        for node in iter_imports(tree):
            for target in sorted(_resolved_import_targets(filesystem, importer_package, node)):
                reason = _test_import_violation(
                    importer,
                    target,
                    paired_source,
                    source_root_lookup,
                    tests_root,
                    common_root_lookup,
                    test_common_lookup,
                )
                if reason is not None:
                    violations.append(
                        RecursiveImportViolation(
                            importer=_relative(repo_root, importer),
                            line=node.lineno,
                            reason=reason,
                            target=_relative(repo_root, target),
                        )
                    )
    return violations


def assert_recursive_import_boundaries(repo_root: Path, layout: ImportBoundaryLayout) -> None:
    """
    Raise with the complete violation list for one consumer repository.
    """
    violations = find_recursive_import_violations(repo_root, layout)
    if violations:
        summary = "\n".join(str(violation) for violation in violations)
        raise AssertionError(
            f"recursive import boundaries require sibling/descendant or explicit common imports:\n{summary}"
        )
