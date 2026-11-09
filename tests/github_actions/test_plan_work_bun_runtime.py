"""plan-work installs Bun for repositories with Bun tests, so their lanes are planned rather than all run."""

import subprocess
from pathlib import Path

import pytest
import yaml

from ci_esta.testing.bun import runtime
from tests.testing.git_repo import commit, write

ROOT = Path(__file__).resolve().parents[2]


def decide(repo: Path, files: dict[str, str], monkeypatch: pytest.MonkeyPatch, bun: str | None) -> dict[str, str]:
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    for name, content in files.items():
        write(repo, name, content)
    commit(repo)
    monkeypatch.setattr(runtime.shutil, "which", lambda name: bun if name == "bun" else None)
    output = repo.parent / f"{repo.name}-output"
    assert runtime.main(["--repo", str(repo), "--github-output", str(output)]) == 0
    return dict(line.split("=", 1) for line in output.read_text(encoding="utf-8").splitlines())


@pytest.mark.parametrize(
    ("files", "expected"),
    [
        # No tests the Bun graph plans: nothing to install.
        ({"README.md": "# docs\n", "tests/test_app.py": "def test_app(): pass\n"}, {"install": "false"}),
        # Bun tests, pinned by each version file oven-sh/setup-bun reads.
        (
            {"web/app.test.ts": "// test\n", ".bun-version": "1.3.14\n"},
            {"install": "true", "version-file": ".bun-version"},
        ),
        (
            {"web/app_spec.mjs": "// test\n", ".tool-versions": "nodejs 24.0.0\nbun 1.3.14\n"},
            {"install": "true", "version-file": ".tool-versions"},
        ),
        (
            {"web/app.test.tsx": "// test\n", "package.json": '{"packageManager": "bun@1.3.14"}\n'},
            {"install": "true", "version-file": "package.json"},
        ),
        # A version file that pins something else is not Bun's: the latest Bun.
        (
            {"web/app.test.js": "// test\n", ".tool-versions": "nodejs 24.0.0\n", "package.json": '{"name": "web"}\n'},
            {"install": "true", "version-file": ""},
        ),
    ],
)
def test_bun_is_installed_only_for_repositories_with_bun_tests(tmp_path, monkeypatch, files, expected):
    assert decide(tmp_path / "repo", files, monkeypatch, bun=None) == expected


def test_a_bun_the_caller_installed_is_kept(tmp_path, monkeypatch):
    assert decide(tmp_path / "repo", {"web/app.test.ts": "// test\n"}, monkeypatch, bun="/usr/bin/bun") == {
        "install": "false"
    }


def test_the_action_installs_bun_only_when_needed_and_never_fails_planning_on_it():
    steps = yaml.safe_load((ROOT / "actions/plan-work/action.yml").read_text(encoding="utf-8"))["runs"]["steps"]
    names = [step.get("id") or step.get("uses") for step in steps]
    setup = next(step for step in steps if str(step.get("uses", "")).startswith("oven-sh/setup-bun@"))
    assert names.index("bun") < names.index(setup["uses"]) < names.index("plan")
    assert setup["if"] == "${{ steps.bun.outputs.install == 'true' }}"
    assert setup["continue-on-error"] is True
    # Both steps run in one uv environment, so the decision adds no second install.
    decide_step, plan_step = (next(step for step in steps if step.get("id") == name) for name in ("bun", "plan"))
    assert decide_step["run"].split("python -m")[0] == plan_step["run"].split("python -m")[0]
