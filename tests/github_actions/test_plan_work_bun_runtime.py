"""plan-work installs Bun for repositories with Bun tests, so their lanes are planned rather than all run."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "actions/plan-work/bun-runtime.sh"


def decide(repo: Path, files: dict[str, str], path: str) -> dict[str, str]:
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    for name, content in files.items():
        (repo / name).parent.mkdir(parents=True, exist_ok=True)
        (repo / name).write_text(content, encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
    output = repo.parent / f"{repo.name}-output"
    output.write_text("", encoding="utf-8")
    bash = shutil.which("bash")
    assert bash is not None
    subprocess.run(
        [bash, SCRIPT.as_posix()], cwd=repo, check=True, env=os.environ | {"GITHUB_OUTPUT": str(output), "PATH": path}
    )
    return dict(line.split("=", 1) for line in output.read_text(encoding="utf-8").splitlines())


def path_without_bun() -> str:
    """PATH with every directory holding a `bun` executable removed."""
    return os.pathsep.join(
        directory
        for directory in os.environ["PATH"].split(os.pathsep)
        if not any((Path(directory) / name).exists() for name in ("bun", "bun.exe"))
    )


@pytest.mark.parametrize(
    ("files", "expected"),
    [
        # No Bun-style tests: nothing to plan with Bun.
        ({"README.md": "# docs\n", "tests/test_app.py": "def test_app(): pass\n"}, {"install": "false"}),
        # Bun-style tests and a pinned version file.
        (
            {"web/app.test.ts": "// test\n", ".bun-version": "1.3.14\n"},
            {"install": "true", "version-file": ".bun-version"},
        ),
        (
            {"web/app_spec.mjs": "// test\n", "package.json": '{"packageManager": "bun@1.3.14"}\n'},
            {"install": "true", "version-file": "package.json"},
        ),
        # No version pinned: the latest Bun.
        (
            {"web/app.test.tsx": "// test\n", "package.json": '{"name": "web"}\n'},
            {"install": "true", "version-file": ""},
        ),
    ],
)
def test_bun_is_installed_only_for_repositories_with_bun_tests(tmp_path, files, expected):
    assert decide(tmp_path / "repo", files, path_without_bun()) == expected


def test_a_bun_the_caller_installed_is_kept(tmp_path):
    shim = tmp_path / "bin"
    shim.mkdir()
    (shim / "bun").write_text("#!/bin/sh\n", encoding="utf-8")
    (shim / "bun").chmod(0o755)
    path = os.pathsep.join([str(shim), path_without_bun()])
    assert decide(tmp_path / "repo", {"web/app.test.ts": "// test\n"}, path) == {"install": "false"}


def test_the_action_installs_bun_only_when_needed_and_never_fails_planning_on_it():
    steps = yaml.safe_load((ROOT / "actions/plan-work/action.yml").read_text(encoding="utf-8"))["runs"]["steps"]
    names = [step.get("id") or step.get("uses") for step in steps]
    setup = next(step for step in steps if str(step.get("uses", "")).startswith("oven-sh/setup-bun@"))
    assert names.index("bun") < names.index(setup["uses"]) < names.index("plan")
    assert setup["if"] == "${{ steps.bun.outputs.install == 'true' }}"
    assert setup["continue-on-error"] is True
