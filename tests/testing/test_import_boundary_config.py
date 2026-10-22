import json
from pathlib import Path

import pytest

from ci_esta.testing.import_boundary_config import ImportBoundaryConfig, load_import_boundary_layout


def _write_layout(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "source_prefix": ["src", "gv", "ai"],
                "isolated_test_tree_mappings": {"tools": "tests/tools"},
                "recursive_service_test_projection": True,
                "common_roots": ["tests/integration"],
                "module_search_roots": ["src", "."],
                "test_source_mappings": {"tests/test_svc_alias": "src/gv/ai/svc"},
            }
        )
    )


def test_combined_config_derives_conventional_and_isolated_boundary_mappings(tmp_path: Path) -> None:
    config = tmp_path / "layout.json"
    _write_layout(config)
    for directory in (
        "src/gv/ai/svc",
        "src/gv/ai/common",
        "tests/test_svc",
        "tests/test_svc_alias",
        "tests/test_common",
        "tests/helpers",
        "tests/integration",
        "tools/gv",
        "tests/tools/gv",
    ):
        (tmp_path / directory).mkdir(parents=True)

    boundaries = load_import_boundary_layout(config, tmp_path)

    assert boundaries.test_source_mappings == {
        Path("tests/test_common"): Path("src/gv/ai/common"),
        Path("tests/test_svc"): Path("src/gv/ai/svc"),
        Path("tests/test_svc_alias"): Path("src/gv/ai/svc"),
        Path("tests/tools/gv"): Path("tools/gv"),
    }
    assert boundaries.source_roots == (Path("src/gv/ai"), Path("tools/gv"))
    assert boundaries.common_roots == (
        Path("src/gv/ai/common"),
        Path("tests/helpers"),
        Path("tests/integration"),
    )


def test_root_test_support_modules_are_inferred_as_common(tmp_path: Path) -> None:
    config = tmp_path / "layout.json"
    _write_layout(config)
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests/__init__.py").write_text("")
    (tmp_path / "tests/conftest.py").write_text("")
    (tmp_path / "tests/_resource_plugin.py").write_text("")
    (tmp_path / "tests/test_root_module.py").write_text("def test_it(): ...\n")

    boundaries = load_import_boundary_layout(config, tmp_path)

    assert Path("tests/__init__.py") in boundaries.common_roots
    assert Path("tests/conftest.py") in boundaries.common_roots
    assert Path("tests/_resource_plugin.py") in boundaries.common_roots
    assert Path("tests/test_root_module.py") not in boundaries.common_roots


def test_unknown_layout_field_is_rejected(tmp_path: Path) -> None:
    config = tmp_path / "layout.json"
    _write_layout(config)
    values = json.loads(config.read_text())
    values["target_tests_per_shard"] = 2_500
    config.write_text(json.dumps(values))

    with pytest.raises(ValueError, match="target_tests_per_shard"):
        load_import_boundary_layout(config, tmp_path)


@pytest.mark.parametrize("explicit_roots", [False, True])
def test_isolated_scripts_are_boundaries_but_filesystem_debris_is_not(tmp_path: Path, explicit_roots: bool) -> None:
    config = ImportBoundaryConfig(
        source_prefix=("src",),
        isolated_test_tree_mappings={"tools": "tests/tools", "absent": "tests/absent"},
        source_roots=(Path("tools"),) if explicit_roots else None,
    )
    for directory in ("tools", "tests/tools/tool", "tests/tools/__pycache__", "tests/tools/.local"):
        (tmp_path / directory).mkdir(parents=True, exist_ok=True)
    for name in ("tool.py", "__init__.py", "README.md"):
        (tmp_path / "tools" / name).write_text("")
    for name in ("__pycache__", ".local"):
        (tmp_path / "tools" / name).mkdir()
    config_path = tmp_path / "layout.json"
    config_path.write_text(config.model_dump_json())

    boundaries = load_import_boundary_layout(config_path, tmp_path)

    assert boundaries.test_source_mappings == {Path("tests/tools/tool"): Path("tools/tool.py")}
    assert boundaries.source_roots == ((Path("tools"),) if explicit_roots else (Path("src"), Path("tools/tool.py")))
