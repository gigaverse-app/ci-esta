"""Execute the action's discovery policy with a controlled Git process boundary."""

# gv:test-dependency: actions/native-windows-git/use_native_windows_git.ps1

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "actions/native-windows-git/use_native_windows_git.ps1"
PWSH = shutil.which("pwsh")
pytestmark = pytest.mark.skipif(PWSH is None, reason="PowerShell is required to execute the Windows action")


@pytest.mark.parametrize("prefix", ["ucrt64", "mingw64", "clangarm64", "mingw32"])
@pytest.mark.parametrize("launcher_dir", ["bin", "cmd"])
@pytest.mark.parametrize("native_state", ["matching", "missing", "different-version", "external", "linked"])
def test_native_git_discovery_preserves_the_installation(
    tmp_path: Path, prefix: str, launcher_dir: str, native_state: str
) -> None:
    root = tmp_path / "Git with spaces"
    launcher = root / launcher_dir / "git.exe"
    native_root = tmp_path / "Other Git" if native_state == "external" else root
    native = native_root / prefix / "bin/git.exe"
    launcher.parent.mkdir(parents=True)
    launcher.touch()
    native.parent.mkdir(parents=True)
    if native_state != "missing":
        native.touch()
    linked_root = tmp_path / "current"
    if native_state == "linked":
        launcher = linked_root / launcher_dir / "git.exe"
    result_path = tmp_path / "result.json"
    wrapper = tmp_path / "exercise.ps1"
    wrapper.write_text(
        """
$ErrorActionPreference = 'Stop'
$originalPath = $env:PATH
if ($env:TEST_NATIVE_STATE -eq 'linked') {
    $kind = if ($IsWindows) { 'Junction' } else { 'SymbolicLink' }
    New-Item -ItemType $kind -Path $env:TEST_LINK -Target $env:TEST_ROOT | Out-Null
}
function Get-Command { param($Name, $CommandType) [pscustomobject]@{ Source = $env:TEST_LAUNCHER } }
# Only process execution is substituted; path discovery and file checks are real.
Set-Item -LiteralPath "Function:$env:TEST_LAUNCHER" -Value {
    $global:LASTEXITCODE = 0
    if ($args[0] -eq '--exec-path') { $env:TEST_EXEC_PATH } else { 'git version fixture' }
}
Set-Item -LiteralPath "Function:$env:TEST_NATIVE" -Value {
    $global:LASTEXITCODE = 0
    if ($env:TEST_NATIVE_STATE -eq 'different-version') { 'git version different' } else { 'git version fixture' }
}
$failed = $false
try { . $env:TEST_SCRIPT } catch { $failed = $true }
@{ failed=$failed; changed=($env:PATH -ne $originalPath); first=$env:PATH.Split([IO.Path]::PathSeparator)[0] } |
    ConvertTo-Json | Set-Content -LiteralPath $env:TEST_RESULT
""",
        encoding="utf-8",
    )
    result = subprocess.run(
        [PWSH, "-NoProfile", "-File", str(wrapper)],
        env={
            **os.environ,
            "TEST_LAUNCHER": str(launcher),
            "TEST_LINK": str(linked_root),
            "TEST_ROOT": str(root),
            "TEST_NATIVE": str(native),
            "TEST_EXEC_PATH": str(native_root / prefix / "libexec/git-core"),
            "TEST_NATIVE_STATE": native_state,
            "TEST_SCRIPT": str(SCRIPT),
            "TEST_RESULT": str(result_path),
            "GITHUB_PATH": str(tmp_path / "github-path"),
        },
        text=True,
        capture_output=True,
        check=True,
    )
    observed = json.loads(result_path.read_text(encoding="utf-8-sig"))
    assert observed["failed"] == (native_state == "different-version"), result.stdout + result.stderr
    expected_native = native_state in {"matching", "linked"}
    assert observed["changed"] == expected_native, result.stdout + result.stderr
    if expected_native:
        assert Path(observed["first"]) == native.parent
        assert Path((tmp_path / "github-path").read_text(encoding="utf-8-sig").strip()) == native.parent
    else:
        assert not (tmp_path / "github-path").exists()
