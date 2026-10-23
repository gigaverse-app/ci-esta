"""Exercise composite action discovery with and without a caller-owned uv."""

import os
import subprocess
from pathlib import Path

import pytest
import yaml


@pytest.mark.parametrize("existing", [True, False])
def test_canary_installs_uv_only_when_the_caller_has_none(tmp_path: Path, existing: bool) -> None:
    action = yaml.safe_load(Path("actions/pytest-failure-canary/action.yml").read_text())
    steps = action["runs"]["steps"]
    discovery = next((step for step in steps if step.get("id") == "caller-uv"), None)
    assert discovery is not None, "The action must discover and preserve the caller toolchain"
    setup = next(step for step in steps if "setup-uv@" in step.get("uses", ""))
    assert setup["if"] == "${{ steps.caller-uv.outputs.available != 'true' }}"
    binary = tmp_path / "uv"
    if existing:
        binary.write_text("#!/bin/sh\necho caller-pinned-uv\n")
        binary.chmod(0o755)
    output = tmp_path / "outputs"
    subprocess.run(
        ["/bin/bash", "-c", discovery["run"]],
        check=True,
        env=os.environ | {"PATH": str(tmp_path), "GITHUB_OUTPUT": str(output)},
    )
    assert output.read_text().strip() == f"available={'true' if existing else 'false'}"
    if existing:
        assert subprocess.check_output([str(binary)], text=True).strip() == "caller-pinned-uv"
