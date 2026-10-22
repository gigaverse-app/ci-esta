import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from ci_esta.testing import import_boundaries
from ci_esta.testing.import_boundaries import (
    ImportBoundaryLayout,
    assert_recursive_import_boundaries,
    find_recursive_import_violations,
)


def _write(repo: Path, relative: str, source: str = "") -> Path:
    path = repo / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")
    return path


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    return _scaffold_repo(tmp_path)


def _scaffold_repo(root: Path) -> Path:
    for package in (
        "src/gv/ai/common",
        "src/gv/ai/service/area/child",
        "src/gv/ai/service/area/cousin",
        "src/gv/ai/service/area/common",
        "src/gv/ai/service/other",
        "tests/test_service/test_area/test_child",
        "tests/test_service/test_area/test_cousin",
        "tests/test_service/test_area/common",
        "tests/helpers",
    ):
        _write(root, f"{package}/__init__.py")
    _write(root, "src/gv/ai/common/shared.py", "VALUE = 1\n")
    _write(root, "src/gv/ai/service/root.py", "VALUE = 1\n")
    _write(root, "src/gv/ai/service/area/local.py", "VALUE = 1\n")
    _write(root, "src/gv/ai/service/area/child/leaf.py", "VALUE = 1\n")
    _write(root, "src/gv/ai/service/area/cousin/peer.py", "VALUE = 1\n")
    _write(root, "src/gv/ai/service/area/common/shared.py", "VALUE = 1\n")
    _write(root, "src/gv/ai/service/other/root.py", "VALUE = 1\n")
    _write(root, "tests/helpers/shared.py", "VALUE = 1\n")
    _write(root, "tests/test_service/test_area/common/builders.py", "VALUE = 1\n")
    return root


@pytest.fixture
def layout() -> ImportBoundaryLayout:
    return ImportBoundaryLayout(
        source_roots=(Path("src/gv/ai"),),
        tests_root=Path("tests"),
        test_source_mappings={Path("tests/test_service"): Path("src/gv/ai/service")},
        common_roots=(Path("src/gv/ai/common"), Path("tests/helpers")),
        module_search_roots=(Path("src"), Path(".")),
    )


def _violations(repo: Path, layout: ImportBoundaryLayout) -> list[str]:
    return [str(violation) for violation in find_recursive_import_violations(repo, layout)]


class TestSourceBoundaries:
    def test_sibling_child_common_and_external_imports_are_allowed(
        self, repo: Path, layout: ImportBoundaryLayout
    ) -> None:
        _write(
            repo,
            "src/gv/ai/service/area/consumer.py",
            "from gv.ai.service.area.local import VALUE\n"
            "from gv.ai.service.area.child.leaf import VALUE\n"
            "from gv.ai.common.shared import VALUE\n"
            "import json\n",
        )

        assert _violations(repo, layout) == []

    @pytest.mark.parametrize(
        ("statement", "target"),
        [
            ("from gv.ai.service.root import VALUE\n", "src/gv/ai/service/root.py"),
            ("from gv.ai.service.area.cousin.peer import VALUE\n", "src/gv/ai/service/area/cousin/peer.py"),
            ("from ..local import VALUE\n", "src/gv/ai/service/area/local.py"),
        ],
    )
    def test_ancestor_and_cousin_imports_are_rejected(
        self, repo: Path, layout: ImportBoundaryLayout, statement: str, target: str
    ) -> None:
        _write(repo, "src/gv/ai/service/area/child/consumer.py", statement)

        violations = _violations(repo, layout)

        assert len(violations) == 1
        assert "source import must point to a sibling or descendant" in violations[0]
        assert target in violations[0]

    def test_from_package_import_resolves_the_child_not_the_parent_init(
        self, repo: Path, layout: ImportBoundaryLayout
    ) -> None:
        _write(repo, "src/gv/ai/service/area/consumer.py", "from gv.ai.service.area.child import leaf\n")

        assert _violations(repo, layout) == []

    def test_unpaired_internal_directory_remains_part_of_its_nearest_declared_tree(
        self, repo: Path, layout: ImportBoundaryLayout
    ) -> None:
        _write(repo, "src/gv/ai/service/internal/consumer.py", "from gv.ai.service.root import VALUE\n")

        assert _violations(repo, layout) == []

    def test_common_may_not_depend_back_on_an_isolated_tree(self, repo: Path, layout: ImportBoundaryLayout) -> None:
        _write(repo, "src/gv/ai/common/shared.py", "from gv.ai.service.root import VALUE\n")

        violations = _violations(repo, layout)

        assert len(violations) == 1
        assert "common source must not depend on an isolated source tree" in violations[0]

    def test_nested_common_is_shared_only_inside_its_parent_tree(
        self, repo: Path, layout: ImportBoundaryLayout
    ) -> None:
        _write(
            repo,
            "src/gv/ai/service/area/child/consumer.py",
            "from gv.ai.service.area.common.shared import VALUE\n",
        )

        assert _violations(repo, layout) == []

    def test_nested_common_is_not_shared_with_a_cousin_tree(self, repo: Path, layout: ImportBoundaryLayout) -> None:
        _write(
            repo,
            "src/gv/ai/service/other/consumer.py",
            "from gv.ai.service.area.common.shared import VALUE\n",
        )

        violations = _violations(repo, layout)

        assert len(violations) == 1
        assert "source import must point to a sibling or descendant" in violations[0]

    def test_nested_common_may_not_depend_on_its_parent_source_tree(
        self, repo: Path, layout: ImportBoundaryLayout
    ) -> None:
        _write(
            repo,
            "src/gv/ai/service/area/common/shared.py",
            "from gv.ai.service.area.local import VALUE\n",
        )

        violations = _violations(repo, layout)

        assert len(violations) == 1
        assert "common source must not depend on an isolated source tree" in violations[0]

    def test_source_may_not_import_tests(self, repo: Path, layout: ImportBoundaryLayout) -> None:
        _write(repo, "tests/test_service/builders.py", "VALUE = 1\n")
        _write(repo, "src/gv/ai/service/consumer.py", "from tests.test_service.builders import VALUE\n")

        violations = _violations(repo, layout)

        assert len(violations) == 1
        assert "source files must not import tests" in violations[0]


class TestTestBoundaries:
    def test_test_imports_only_its_sibling_source_tree_and_shared_code(
        self, repo: Path, layout: ImportBoundaryLayout
    ) -> None:
        _write(
            repo,
            "tests/test_service/test_area/test_child/test_leaf.py",
            "from gv.ai.service.area.child.leaf import VALUE\n"
            "from gv.ai.common.shared import VALUE\n"
            "from tests.helpers.shared import VALUE\n",
        )

        assert _violations(repo, layout) == []

    @pytest.mark.parametrize(
        ("statement", "target"),
        [
            ("from gv.ai.service.area.local import VALUE\n", "src/gv/ai/service/area/local.py"),
            ("from gv.ai.service.area.cousin.peer import VALUE\n", "src/gv/ai/service/area/cousin/peer.py"),
        ],
    )
    def test_test_source_imports_above_or_beside_the_sibling_tree_are_rejected(
        self, repo: Path, layout: ImportBoundaryLayout, statement: str, target: str
    ) -> None:
        _write(repo, "tests/test_service/test_area/test_child/test_leaf.py", statement)

        violations = _violations(repo, layout)

        assert len(violations) == 1
        assert "test import must stay in its sibling source subtree" in violations[0]
        assert target in violations[0]

    def test_test_helpers_must_be_siblings_descendants_or_explicitly_common(
        self, repo: Path, layout: ImportBoundaryLayout
    ) -> None:
        _write(repo, "tests/test_service/test_area/builders.py", "VALUE = 1\n")
        _write(
            repo,
            "tests/test_service/test_area/test_child/test_leaf.py",
            "from tests.test_service.test_area.builders import VALUE\n",
        )

        violations = _violations(repo, layout)

        assert len(violations) == 1
        assert "test support import must point to a sibling or descendant" in violations[0]

    def test_parent_conftest_is_shared_with_descendant_tests(self, repo: Path, layout: ImportBoundaryLayout) -> None:
        _write(repo, "tests/test_service/test_area/conftest.py", "VALUE = 1\n")
        _write(
            repo,
            "tests/test_service/test_area/test_child/test_leaf.py",
            "from tests.test_service.test_area.conftest import VALUE\n",
        )

        assert _violations(repo, layout) == []

    def test_nested_test_common_is_shared_only_inside_its_parent_tree(
        self, repo: Path, layout: ImportBoundaryLayout
    ) -> None:
        _write(
            repo,
            "tests/test_service/test_area/test_child/test_leaf.py",
            "from tests.test_service.test_area.common.builders import VALUE\n",
        )

        assert _violations(repo, layout) == []

    def test_nested_test_common_is_not_shared_with_a_cousin_tree(
        self, repo: Path, layout: ImportBoundaryLayout
    ) -> None:
        _write(
            repo,
            "tests/test_service/test_other/test_leaf.py",
            "from tests.test_service.test_area.common.builders import VALUE\n",
        )

        violations = _violations(repo, layout)

        assert len(violations) == 1
        assert "test support import must point to a sibling or descendant" in violations[0]

    def test_unmapped_test_tree_is_rejected(self, repo: Path, layout: ImportBoundaryLayout) -> None:
        _write(repo, "tests/test_unknown/test_something.py", "def test_it(): ...\n")

        violations = _violations(repo, layout)

        assert len(violations) == 1
        assert "is outside every test/source mapping and common root" in violations[0]

    def test_unmapped_package_marker_does_not_claim_test_ownership(
        self, repo: Path, layout: ImportBoundaryLayout
    ) -> None:
        _write(repo, "tests/organizational/__init__.py")

        assert _violations(repo, layout) == []

    def test_nested_test_directory_requires_a_real_sibling_source_directory(
        self, repo: Path, layout: ImportBoundaryLayout
    ) -> None:
        _write(repo, "tests/test_service/test_missing/test_something.py", "def test_it(): ...\n")

        violations = _violations(repo, layout)

        assert len(violations) == 1
        assert "has no sibling source directory src/gv/ai/service/missing" in violations[0]

    def test_plain_test_organization_directory_does_not_claim_a_source_boundary(
        self, repo: Path, layout: ImportBoundaryLayout
    ) -> None:
        _write(
            repo,
            "tests/test_service/integration/test_something.py",
            "from gv.ai.service.root import VALUE\n",
        )

        assert _violations(repo, layout) == []


def test_assertion_lists_all_boundary_violations(repo: Path, layout: ImportBoundaryLayout) -> None:
    _write(
        repo,
        "src/gv/ai/service/area/child/consumer.py",
        "from gv.ai.service.root import VALUE\nfrom gv.ai.service.area.cousin.peer import VALUE\n",
    )

    with pytest.raises(AssertionError, match="recursive import boundaries") as excinfo:
        assert_recursive_import_boundaries(repo, layout)

    assert "service/root.py" in str(excinfo.value)
    assert "cousin/peer.py" in str(excinfo.value)


SINGLE_IMPORTER_COUNT = 1
REPEATED_IMPORTER_COUNT = 25
REPEATED_IMPORT_SOURCE = "from gv.ai.service.area.local import VALUE\nimport gv.ai.common.shared\n"


def _module_probe_count(repo: Path, layout: ImportBoundaryLayout, importer_count: int) -> int:
    for index in range(importer_count):
        _write(repo, f"src/gv/ai/service/area/consumer_{index}.py", REPEATED_IMPORT_SOURCE)
    with patch.object(import_boundaries, "_module_file", wraps=import_boundaries._module_file) as probe:
        assert _violations(repo, layout) == []
    return probe.call_count


class TestScanFilesystemWork:
    def test_each_module_name_is_probed_once_per_scan_however_many_statements_import_it(
        self, tmp_path: Path, layout: ImportBoundaryLayout
    ) -> None:
        """Filesystem probes scale with distinct module names, not with import statements."""
        single = _module_probe_count(_scaffold_repo(tmp_path / "single"), layout, SINGLE_IMPORTER_COUNT)
        repeated = _module_probe_count(_scaffold_repo(tmp_path / "repeated"), layout, REPEATED_IMPORTER_COUNT)

        assert single > 0
        assert repeated == single

    def test_separate_scans_do_not_share_module_resolution(self, repo: Path, layout: ImportBoundaryLayout) -> None:
        _write(repo, "src/gv/ai/service/area/child/consumer.py", "from gv.ai.service.area.cousin.late import VALUE\n")
        assert _violations(repo, layout) == []

        _write(repo, "src/gv/ai/service/area/cousin/late.py", "VALUE = 1\n")
        violations = _violations(repo, layout)

        assert len(violations) == 1
        assert "src/gv/ai/service/area/cousin/late.py" in violations[0]

    @pytest.mark.skipif(sys.platform == "win32", reason="creating symlinks needs elevated rights on Windows")
    def test_symlinked_module_is_judged_by_its_canonical_target(self, repo: Path, layout: ImportBoundaryLayout) -> None:
        (repo / "src/gv/ai/service/area/child/alias.py").symlink_to(repo / "src/gv/ai/service/root.py")
        _write(repo, "src/gv/ai/service/area/child/consumer.py", "from gv.ai.service.area.child.alias import VALUE\n")

        violations = _violations(repo, layout)

        assert len(violations) == 1
        assert "source import must point to a sibling or descendant" in violations[0]
        assert violations[0].endswith("-> src/gv/ai/service/root.py")
