"""Resolve consumer naming conventions into the canonical import-boundary layout."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field
from pytest_selective.test_inventory import is_test_module_name

from ci_esta.testing.import_boundaries import ImportBoundaryLayout


class ImportBoundaryConfig(BaseModel):
    """Consumer JSON contract for conventional service/test directory projections."""

    model_config = ConfigDict(extra="forbid")

    source_prefix: tuple[str, ...]
    non_service_source_dirs: frozenset[str] = frozenset({"common", "__pycache__"})
    shared_source_dirs: tuple[str, ...] = ("common",)
    shared_test_infra_dirs: frozenset[str] = frozenset({"fakes", "fixtures", "helpers", "test_data"})
    service_test_dir_overrides: dict[str, str] = Field(default_factory=dict)
    service_test_dir_template: str = "test_{service}"
    isolated_test_tree_mappings: dict[str, str] = Field(default_factory=dict)
    test_source_mappings: dict[str, str] = Field(default_factory=dict)
    recursive_service_test_projection: bool = False
    test_directory_prefix: str = "test_"
    tests_root: str = "tests"
    source_roots: tuple[Path, ...] | None = None
    common_roots: tuple[Path, ...] = ()
    module_search_roots: tuple[Path, ...] = (Path("src"), Path("."))

    def source_root(self, repo_root: Path) -> Path:
        return repo_root.joinpath(*self.source_prefix)

    def test_dir_for_service(self, service: str) -> str:
        return self.service_test_dir_overrides.get(service, self.service_test_dir_template.format(service=service))


def discover_services(repo_root: Path, layout: ImportBoundaryConfig) -> list[str]:
    source_root = layout.source_root(repo_root)
    if not source_root.is_dir():
        return []
    return sorted(
        entry.name
        for entry in source_root.iterdir()
        if entry.is_dir() and entry.name not in layout.non_service_source_dirs
    )


def discover_test_source_mappings(
    repo_root: Path,
    layout: ImportBoundaryConfig,
) -> dict[Path, Path]:
    """Infer architecture boundaries from conventions and explicit aliases."""
    mappings: dict[Path, Path] = {}
    if layout.recursive_service_test_projection:
        source_root = Path(*layout.source_prefix)
        for service in discover_services(repo_root, layout):
            test_root = Path(layout.tests_root, layout.test_dir_for_service(service))
            if (repo_root / test_root).is_dir():
                mappings[test_root] = source_root / service

        for shared_dir in layout.shared_source_dirs:
            shared_source = source_root / shared_dir
            test_root = Path(layout.tests_root, layout.service_test_dir_template.format(service=shared_dir))
            if (repo_root / shared_source).is_dir() and (repo_root / test_root).is_dir():
                mappings[test_root] = shared_source

    for source_prefix, test_prefix in sorted(layout.isolated_test_tree_mappings.items()):
        absolute_source = repo_root / source_prefix
        if not absolute_source.is_dir():
            continue
        for child in sorted(absolute_source.iterdir()):
            # Runtime caches and hidden tool state are filesystem debris,
            # not independently owned source trees.
            if child.name == "__pycache__" or child.name.startswith("."):
                continue
            if child.is_dir():
                unit = child.name
            elif child.is_file() and child.suffix == ".py" and child.name != "__init__.py":
                unit = child.stem
            else:
                continue
            test_root = Path(test_prefix, unit)
            if (repo_root / test_root).is_dir():
                mappings[test_root] = Path(source_prefix, child.name)

    mappings.update(
        {
            Path(test_root): Path(source_root)
            for test_root, source_root in layout.test_source_mappings.items()
            if (repo_root / test_root).is_dir()
        }
    )
    return dict(sorted(mappings.items(), key=lambda item: str(item[0])))


def load_import_boundary_layout(config_path: Path, repo_root: Path) -> ImportBoundaryLayout:
    """Resolve the boundary checker configuration without selecting tests."""
    config = ImportBoundaryConfig.model_validate_json(config_path.read_text(encoding="utf-8"))
    mappings = discover_test_source_mappings(repo_root, config)
    declared_source_roots = config.source_roots
    if declared_source_roots is None:
        candidates = {Path(*config.source_prefix), *mappings.values()}
        source_roots = tuple(
            sorted(
                (
                    candidate
                    for candidate in candidates
                    if not any(candidate != other and candidate.is_relative_to(other) for other in candidates)
                ),
                key=str,
            )
        )
    else:
        source_roots = declared_source_roots
    inferred_common_roots = {
        Path(*config.source_prefix, shared_dir)
        for shared_dir in config.shared_source_dirs
        if (repo_root / Path(*config.source_prefix, shared_dir)).is_dir()
    }
    inferred_common_roots.update(
        Path(config.tests_root, shared_dir)
        for shared_dir in config.shared_test_infra_dirs
        if (repo_root / config.tests_root / shared_dir).is_dir()
    )
    tests_root = repo_root / config.tests_root
    if tests_root.is_dir():
        inferred_common_roots.update(
            candidate.relative_to(repo_root)
            for candidate in tests_root.iterdir()
            if candidate.is_file() and candidate.suffix == ".py" and not is_test_module_name(candidate.name)
        )
    declared_common_roots = set(config.common_roots)
    return ImportBoundaryLayout(
        source_roots=source_roots,
        tests_root=Path(config.tests_root),
        test_source_mappings=mappings,
        common_roots=tuple(sorted(inferred_common_roots | declared_common_roots, key=str)),
        module_search_roots=config.module_search_roots,
        test_directory_prefix=config.test_directory_prefix,
    )
