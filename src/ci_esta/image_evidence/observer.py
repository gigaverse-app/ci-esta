"""Freeze the current inspector and consumer policy for historical-image probes."""

from __future__ import annotations

import ast
import hashlib
import zipfile
from pathlib import Path

from ci_esta.image_evidence import runtime


def write_observer(adapter: Path, output: Path) -> str:
    """
    Build a deterministic stdlib-only zipapp; return its SHA256 identity.

    Relocate only the inspector import into the archive's private module. Never
    shadow backend_common itself: the consumer must still inspect the package
    installed in the image. The source module remains the one shared owner, while
    this archive can run on images predating that API.
    """
    assert runtime.__file__ is not None
    tree = ast.parse(adapter.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module in {
            "ci_esta.image_evidence.runtime", "backend_common.image_evidence.runtime"
        }:
            node.module = "_gv_image_runtime"
    files = {
        "__main__.py": (ast.unparse(tree) + "\n").encode(),
        "_gv_image_runtime.py": Path(runtime.__file__).read_bytes(),
    }
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, content in files.items():
            info = zipfile.ZipInfo(name, date_time=(2020, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, content)
    return hashlib.sha256(output.read_bytes()).hexdigest()
