"""The typecheck-scope action: a scoped check needs a proven-clean base, and every doubt is the full check."""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
ACTION = ROOT / ".github/actions/typecheck-scope"
BASE = "b" * 40


def proven(check_runs: list[dict[str, str]], names: list[str]) -> bool:
    script = "const {provenClean}=require(process.argv[1]); console.log(JSON.stringify(provenClean(JSON.parse(process.argv[2]), JSON.parse(process.argv[3]))));"
    result = subprocess.run(
        ["node", "-e", script, str(ACTION / "proof.cjs"), json.dumps(check_runs), json.dumps(names)],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)


def run(name: str, conclusion: str, at: str = "2026-09-24T10:00:00Z", status: str = "completed") -> dict[str, str]:
    return {"name": name, "conclusion": conclusion, "status": status, "completed_at": at}


@pytest.mark.parametrize(
    ("runs", "expected"),
    [
        ([run("basedpyright", "success")], True),
        ([run("type-check / basedpyright", "success")], True),
        ([run("basedpyright", "failure")], False),
        ([run("basedpyright", "skipped")], False),
        ([run("basedpyright", "success", status="in_progress")], False),
        ([run("unit tests", "success")], False),
        ([], False),
        # A later failed rerun of the same check revokes the earlier success.
        (
            [
                run("basedpyright", "success", "2026-09-24T10:00:00Z"),
                run("basedpyright", "failure", "2026-09-24T11:00:00Z"),
            ],
            False,
        ),
        (
            [
                run("basedpyright", "failure", "2026-09-24T10:00:00Z"),
                run("basedpyright", "success", "2026-09-24T11:00:00Z"),
            ],
            True,
        ),
    ],
    ids=["success", "reusable-name", "failure", "skipped", "running", "other-check", "none", "revoked", "fixed"],
)
def test_only_a_newest_successful_checker_run_proves_the_base_clean(runs: list[dict[str, str]], expected: bool) -> None:
    """INVARIANT: a scoped check assumes a clean base, so only that checker's own success on it proves one."""
    assert proven(runs, ["basedpyright", "type-check / basedpyright"]) is expected


def execute(tmp_path: Path, *, proven_base: str, git_ok: bool, uv: str) -> dict[str, str]:
    """Run scope.sh with git and uv stubbed at the process boundary; return its GitHub outputs."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "git").write_text(f"#!/bin/bash\nexit {0 if git_ok else 1}\n")
    (bin_dir / "uv").write_text(f"#!/bin/bash\n{uv}\n")
    for tool in bin_dir.iterdir():
        tool.chmod(0o755)
    output = tmp_path / "github-output"
    output.write_text("")
    bash = shutil.which("bash")
    assert bash is not None
    subprocess.run(
        [bash, str(ACTION / "scope.sh")],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
            "GITHUB_OUTPUT": str(output),
            "SCOPE_PROVEN": proven_base,
            "SCOPE_CONFIG": "impact.json",
            "SCOPE_BASE": BASE,
            "SCOPE_HEAD": "HEAD",
            "SCOPE_CHECKER_CONFIG": "pyrightconfig.json",
            "SCOPE_GLOBAL_INPUTS": "uv.lock *.pyi",
            "SCOPE_MAX_FRACTION": "0.6",
            "SHARED_ACTION_PATH": str(ACTION),
        },
    )
    text = output.read_text()
    outputs: dict[str, str] = {}
    lines = iter(text.splitlines())
    for line in lines:
        if "<<" in line and "=" not in line.split("<<", 1)[0]:
            key, delimiter = line.split("<<", 1)
            outputs[key] = "\n".join(iter(lambda: next(lines), delimiter))
        elif "=" in line:
            key, value = line.split("=", 1)
            outputs[key] = value
    return outputs


SCOPED = 'printf "mode=scoped\\nfiles=2\\nreason=2 of 9\\n" > typecheck-scope.env; printf "a.py\\nb.py\\n" > typecheck-scope.txt'


@pytest.mark.parametrize(
    ("proven_base", "git_ok", "uv", "reason"),
    [
        ("false", True, SCOPED, "no successful clean-base check run"),
        ("true", False, SCOPED, "could not fetch base"),
        ("true", True, "exit 1", "scope computation failed"),
        ("true", True, "exit 0", "wrote no result"),
        (
            "true",
            True,
            'printf "mode=full\\nfiles=0\\nreason=global inputs changed: uv.lock\\n" > typecheck-scope.env',
            "uv.lock",
        ),
    ],
    ids=["unproven-base", "fetch-failed", "cli-failed", "no-result", "cli-full"],
)
def test_every_doubt_is_the_full_check(tmp_path: Path, proven_base: str, git_ok: bool, uv: str, reason: str) -> None:
    outputs = execute(tmp_path, proven_base=proven_base, git_ok=git_ok, uv=uv)
    assert outputs["mode"] == "full"
    assert reason in outputs["reason"]
    assert outputs["paths"] == ""


def test_a_proven_scope_is_handed_to_the_checker(tmp_path: Path) -> None:
    outputs = execute(tmp_path, proven_base="true", git_ok=True, uv=SCOPED)
    assert outputs["mode"] == "scoped"
    assert outputs["paths"].split() == ["a.py", "b.py"]


def test_check_names_with_spaces_survive_the_input() -> None:
    """A whitespace split turned `type-check / basedpyright` into three names that match nothing."""
    script = "const {checkNames}=require(process.argv[1]); console.log(JSON.stringify(checkNames(process.argv[2])));"
    text = "basedpyright\n  type-check / basedpyright  \n\n"
    result = subprocess.run(
        ["node", "-e", script, str(ACTION / "proof.cjs"), text], check=True, capture_output=True, text=True
    )
    assert json.loads(result.stdout) == ["basedpyright", "type-check / basedpyright"]
