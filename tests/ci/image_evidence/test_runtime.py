"""Actual files and CPython artifacts pin the portable observer's contract."""

import importlib.util
import os
import py_compile
import subprocess
import sys
from pathlib import Path

import pytest

from ci_esta.image_evidence.observer import write_observer
from ci_esta.image_evidence.runtime import file_inventory, validate_bytecode


@pytest.mark.parametrize("mode", list(py_compile.PycInvalidationMode))
def test_compiled_content_is_checked_even_with_matching_source_metadata(
    tmp_path: Path, mode: py_compile.PycInvalidationMode
) -> None:
    source = tmp_path / "module.py"
    source.write_text("value = 1\n")
    py_compile.compile(str(source), doraise=True, invalidation_mode=mode)
    validate_bytecode(source)
    before = source.stat()
    source.write_text("value = 2\n")
    os.utime(source, ns=(before.st_atime_ns, before.st_mtime_ns))
    with pytest.raises(AssertionError):
        validate_bytecode(source)


def test_missing_wrong_path_and_invalid_bytecode_reject(tmp_path: Path) -> None:
    source = tmp_path / "module.py"
    source.write_text("value = 1\n")
    with pytest.raises(FileNotFoundError):
        validate_bytecode(source)
    py_compile.compile(str(source), dfile="/wrong/module.py", doraise=True)
    with pytest.raises(AssertionError):
        validate_bytecode(source)
    compiled = Path(importlib.util.cache_from_source(str(source)))
    compiled.write_bytes(b"bad")
    with pytest.raises(AssertionError):
        validate_bytecode(source)


def test_fingerprints_retain_modes_links_metadata_and_explicit_exclusion_policy(tmp_path: Path) -> None:
    script = tmp_path / "bin"
    script.write_text("script")
    link = tmp_path / "link"
    link.symlink_to("missing")
    metadata = tmp_path / "pkg.dist-info"
    metadata.mkdir()
    for name in ("RECORD", "uv_cache.json", "METADATA", "entry_points.txt", "direct_url.json"):
        (metadata / name).write_text(name)
    (tmp_path / "module.pyc").write_bytes(b"compiled")
    initial = file_inventory(tmp_path, installed=True)
    assert initial["link"]["symlink"] == "missing"
    assert "pkg.dist-info/RECORD" not in initial and "module.pyc" not in initial
    assert "pkg.dist-info/direct_url.json" in initial
    assert "module.pyc" in file_inventory(tmp_path)
    assert "pkg.dist-info/RECORD" in file_inventory(tmp_path)
    script.chmod(0o700)
    assert file_inventory(tmp_path, installed=True) != initial
    script.unlink()
    assert "bin" not in file_inventory(tmp_path)
    assert set(file_inventory(tmp_path, recursive=False)) == {"link", "module.pyc"}


def test_observer_freezes_one_shared_implementation_without_installed_dependencies(tmp_path: Path) -> None:
    adapter = tmp_path / "adapter.py"
    adapter.write_text(
        "from ci_esta.image_evidence.runtime import file_inventory\n"
        "from pathlib import Path\n"
        "import sys\n"
        "assert sys.dont_write_bytecode\n"
        "assert file_inventory(Path(sys.argv[1])) == {}\n"
        "print('portable observer passed')\n"
    )
    empty = tmp_path / "empty"
    empty.mkdir()
    archive = tmp_path / "observer.pyz"
    digest = write_observer(adapter, archive)
    other = tmp_path / "other.pyz"
    assert write_observer(adapter, other) == digest
    assert archive.read_bytes() == other.read_bytes()
    adapter.unlink()  # Execution cannot reread a changed consumer checkout.
    result = subprocess.run(
        [sys.executable, "-I", "-S", "-B", str(archive), str(empty)], text=True, capture_output=True, check=True
    )
    assert result.stdout.strip() == "portable observer passed"


@pytest.mark.parametrize("namespace", ["ci_esta", "backend_common"])
def test_frozen_helpers_do_not_shadow_the_installed_package_under_inspection(tmp_path: Path, namespace: str) -> None:
    site = tmp_path / "site"
    package = site / "backend_common"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("INSTALLED_SENTINEL = 'historical-image'\n")
    adapter = tmp_path / "adapter.py"
    adapter.write_text(
        "import sys\n"
        "sys.path.append(sys.argv[1])\n"
        f"from {namespace}.image_evidence.runtime import file_inventory\n"
        "import backend_common\n"
        "assert backend_common.INSTALLED_SENTINEL == 'historical-image'\n"
    )
    archive = tmp_path / "probe.pyz"
    write_observer(adapter, archive)
    subprocess.run([sys.executable, "-I", "-S", "-B", str(archive), str(site)], check=True)
