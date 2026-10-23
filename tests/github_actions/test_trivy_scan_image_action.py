from pathlib import Path

import yaml

ACTION_PATH = Path("actions/trivy-scan-image/action.yml")
LATEST_TRIVY_VERSION = "v0.72.0"
TRIVY_VERSION_INPUT = "trivy-version"


def test_trivy_version_default_is_forwarded_to_trivy_action() -> None:
    action = ACTION_PATH.read_text()

    assert f"{TRIVY_VERSION_INPUT}:\n" in action
    assert f'default: "{LATEST_TRIVY_VERSION}"' in action
    assert f"version: ${{{{ inputs.{TRIVY_VERSION_INPUT} }}}}" in action


def test_trivy_inventory_kind_is_forwarded_without_duplicating_policy() -> None:
    """INVARIANT: image and filesystem inventories share one vulnerability policy."""
    action = yaml.safe_load(ACTION_PATH.read_text())
    inputs = action["inputs"]
    trivy = action["runs"]["steps"][0]["with"]

    assert inputs["scan-type"]["default"] == "image"
    assert inputs["scan-ref"]["default"] == "."
    assert inputs["vuln-type"]["default"] == "os,library"
    assert inputs["scanners"]["default"] == "vuln"
    assert inputs["image-ref"]["required"] is False

    for name in (
        "scan-type",
        "scan-ref",
        "image-ref",
        "vuln-type",
        "scanners",
        "skip-dirs",
        "cache",
        "skip-setup-trivy",
    ):
        assert trivy[name] == f"${{{{ inputs.{name} }}}}"


def test_python_inventory_examples_delegate_resolution_to_native_package_manager() -> None:
    """INVARIANT: uv and Poetry resolve their own groups/markers before rootfs scanning."""
    readme = Path("actions/README.md").read_text()

    assert "uv sync --frozen --all-groups --no-install-project" in readme
    assert "poetry install --all-groups --no-root" in readme
    assert readme.count("scan-type: rootfs") >= 2
