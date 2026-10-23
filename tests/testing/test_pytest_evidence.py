"""Exercise evidence admission with actual Git trees, reports and shell commands."""

import os
import subprocess
from pathlib import Path

import pytest
import yaml
from pydantic import BaseModel

from ci_esta.testing.canary_action import CanaryConfig, build_canary

ROOT = Path(__file__).resolve().parents[2]
COLLECT = ROOT / "src/ci_esta/testing/evidence_scripts/collect.sh"
RECEIPT = ROOT / "src/ci_esta/testing/evidence_scripts/verify.sh"
VERIFY_ACTION = ROOT / "actions/verify-pytest-completion/action.yml"


class History(BaseModel):
    repo: Path
    old: str
    head: str
    base: str


def git(repo: Path, *args: str) -> str:
    result = subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True)
    return result.stdout.strip()


@pytest.fixture
def history(tmp_path: Path) -> History:
    git(tmp_path, "init", "-q", "-b", "main")
    git(tmp_path, "config", "user.name", "CI test")
    git(tmp_path, "config", "user.email", "ci@example.test")
    git(tmp_path, "remote", "add", "origin", str(tmp_path))
    (tmp_path / "shared.py").write_text("VALUE = 1\n")
    git(tmp_path, "add", ".")
    git(tmp_path, "commit", "-qm", "baseline")
    git(tmp_path, "checkout", "-qb", "feature")
    (tmp_path / "feature.py").write_text("FEATURE = 1\n")
    git(tmp_path, "add", ".")
    git(tmp_path, "commit", "-qm", "previous tested head")
    old = git(tmp_path, "rev-parse", "HEAD")
    git(tmp_path, "checkout", "-q", "main")
    (tmp_path / "shared.py").write_text("VALUE = 2\n")
    git(tmp_path, "commit", "-qam", "imported dependency changed")
    base = git(tmp_path, "rev-parse", "HEAD")
    git(tmp_path, "checkout", "-q", "feature")
    git(tmp_path, "merge", "--no-edit", "main")
    (tmp_path / "feature.py").write_text("FEATURE = 2\n")
    git(tmp_path, "commit", "-qam", "new PR change")
    (tmp_path / "complete-pr-paths.txt").write_text("feature.py\n")
    return History(repo=tmp_path, old=old, head=git(tmp_path, "rev-parse", "HEAD"), base=base)


def collect(history: History, **overrides: str) -> dict[str, str]:
    output = history.repo / "outputs"
    output.write_text("")
    subprocess.run(
        ["bash", str(COLLECT)],
        cwd=history.repo,
        env={
            **os.environ,
            "EVENT_NAME": "pull_request",
            "CURRENT_SHA": history.head,
            "PR_BASE_SHA": history.base,
            "PR_INCREMENTAL_BASE_SHA": "",
            "GITHUB_OUTPUT": str(output),
            **overrides,
        },
        check=True,
        capture_output=True,
        text=True,
    )
    return dict(line.split("=", 1) for line in output.read_text().splitlines())


def test_merge_delta_includes_imported_dependencies_outside_pr_diff(history: History) -> None:
    result = collect(history, PR_INCREMENTAL_BASE_SHA=history.old)
    assert result["base"] == history.old
    assert (history.repo / "changed-files.txt").read_text().splitlines() == ["feature.py", "shared.py"]


def test_validated_tree_offers_the_pr_base_as_the_alternate(history: History) -> None:
    """
    INVARIANT: a validated-tree base always travels with the PR base as its alternate.

    The tree delta includes main's changes merged since that tree was tested; the PR base
    does not. The selector keeps whichever of the two selects fewer tests.
    """
    result = collect(history, PR_INCREMENTAL_BASE_SHA=history.old)
    assert result["alternate-base"] == history.base
    assert (history.repo / "alternate-changed-files.txt").read_text().splitlines() == ["feature.py"]


@pytest.mark.parametrize("candidate", ["", "d" * 40], ids=["no-candidate", "unfetchable"])
def test_pr_base_selection_offers_no_alternate(history: History, candidate: str) -> None:
    (history.repo / "alternate-changed-files.txt").write_text("stale.py\n")
    result = collect(history, PR_INCREMENTAL_BASE_SHA=candidate)
    assert result["base"] == history.base
    assert result["alternate-base"] == ""
    assert not (history.repo / "alternate-changed-files.txt").exists(), "a stale list must not reach the selector"


def test_merge_conflict_resolution_is_a_changed_input(history: History) -> None:
    git(history.repo, "checkout", "-qb", "conflict", history.old)
    (history.repo / "shared.py").write_text("VALUE = 3\n")
    git(history.repo, "commit", "-qam", "branch dependency change")
    tested = git(history.repo, "rev-parse", "HEAD")
    merge = subprocess.run(["git", "merge", "--no-edit", "main"], cwd=history.repo, capture_output=True)
    assert merge.returncode == 1
    (history.repo / "shared.py").write_text("VALUE = 4\n")
    git(history.repo, "add", "shared.py")
    git(history.repo, "commit", "-qm", "resolve dependency conflict")
    resolved = history.model_copy(update={"head": git(history.repo, "rev-parse", "HEAD")})
    result = collect(resolved, PR_INCREMENTAL_BASE_SHA=tested)
    assert result["base"] == tested
    assert (history.repo / "changed-files.txt").read_text().splitlines() == ["shared.py"]


def test_unfetchable_candidate_cannot_change_selector_base(history: History) -> None:
    result = collect(history, PR_INCREMENTAL_BASE_SHA="d" * 40)
    assert result["base"] == history.base
    assert (history.repo / "changed-files.txt").read_text().splitlines() == ["feature.py"]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("FAILURES_COMPLETE", "false"),
        ("FAILURES_TRUNCATED", "true"),
        ("FAILURES_STALE", "1"),
        ("FAILURES_INVALID", "1"),
        ("FAILURES_COUNT", "0"),
    ],
)
def test_partial_failed_run_proof_cannot_adopt_its_base(history: History, field: str, value: str) -> None:
    failure_file = history.repo / "unresolved.txt"
    failure_file.write_text("tests/test_failure.py\n")
    proof = {
        "FAILED_SHA": history.old,
        "FAILURES_FILE": str(failure_file),
        "FAILURES_COMPLETE": "true",
        "FAILURES_TRUNCATED": "false",
        "FAILURES_STALE": "0",
        "FAILURES_INVALID": "0",
        "FAILURES_COUNT": "1",
    }
    control = collect(history, **proof)
    assert control == {"base": history.old, "reused-failures": "true", "alternate-base": history.base}
    proof[field] = value
    result = collect(history, **proof)
    assert result == {"base": history.base, "reused-failures": "false", "alternate-base": ""}
    assert (history.repo / "changed-files.txt").read_text().splitlines() == ["feature.py"]


@pytest.mark.parametrize("damage", [None, "missing", "malformed", "invalid-path", "stale-path"])
def test_failed_evidence_keeps_all_files_or_falls_back(history: History, damage: str | None) -> None:
    reports = history.repo / "reports"
    reports.mkdir()
    tests = history.repo / "tests"
    tests.mkdir()
    # More than the old five-file canary bound: the sixth failure must survive.
    failing_files = [f"tests/test_failure_{number}.py" for number in range(6)]
    for file in failing_files:
        (history.repo / file).write_text("def test_value(): assert False\n")
    cases = "".join(f'<testcase file="{file}"><failure /></testcase>' for file in failing_files)
    first = reports / "junit-group-1.xml"
    first.write_text(f"<testsuite>{cases}</testsuite>")
    (reports / "junit-group-2.xml").write_text("<testsuite><testcase name='passed'/></testsuite>")
    if damage == "missing":
        first.unlink()
    elif damage == "malformed":
        first.write_text("<testsuite>")
    elif damage == "invalid-path":
        first.write_text('<testsuite><testcase file="../escape.py"><failure/></testcase></testsuite>')
    elif damage == "stale-path":
        (history.repo / failing_files[0]).unlink()
    failure_file = history.repo / "unresolved.txt"
    evidence = build_canary(
        CanaryConfig(
            artifact_directory=reports,
            junit_pattern="junit-group-*.xml",
            shard_count=2,
            max_files=2147483647,
            working_directory=history.repo,
            output=failure_file,
        )
    )
    result = collect(
        history,
        FAILED_SHA=history.old,
        FAILURES_FILE=str(failure_file),
        FAILURES_COMPLETE=str(evidence.artifacts_complete).lower(),
        FAILURES_TRUNCATED=str(evidence.truncated).lower(),
        FAILURES_STALE=str(evidence.stale_file_count),
        FAILURES_INVALID=str(evidence.invalid_path_count),
        FAILURES_COUNT=str(evidence.terminal_failure_count),
    )
    selected = (history.repo / "changed-files.txt").read_text().splitlines()
    if damage is None:
        assert result == {"base": history.old, "reused-failures": "true", "alternate-base": history.base}
        assert selected == ["feature.py", "shared.py", *failing_files]
        alternate = (history.repo / "alternate-changed-files.txt").read_text().splitlines()
        assert alternate == ["feature.py", *failing_files], "unresolved failures must follow the PR base"
    else:
        assert result == {"base": history.base, "reused-failures": "false", "alternate-base": ""}
        assert selected == ["feature.py"]


@pytest.mark.parametrize("status", [0, 1, 2, 3, 4, 5, 137, None])
@pytest.mark.parametrize("mode", ["scoped", "full"])
def test_completion_receipt_requires_every_shard_to_finish(tmp_path: Path, status: int | None, mode: str) -> None:
    (tmp_path / "junit-group-1.xml").write_text("<testsuite/>")
    (tmp_path / "junit-group-2.xml").write_text("<testsuite/>")
    (tmp_path / "pytest-status-group-1").write_text("0\n")
    if status is not None:
        (tmp_path / "pytest-status-group-2").write_text(f"{status}\n")
    result = subprocess.run(
        ["bash", str(RECEIPT)],
        cwd=tmp_path,
        env={**os.environ, "PLAN_SHARD_COUNT": "2", "PLAN_MODE": mode},
        capture_output=True,
        text=True,
    )
    assert (result.returncode == 0) == (status in {0, 1} or status == 5 and mode == "scoped")


@pytest.mark.parametrize("finished_shards", [2, 1])
def test_completion_action_verifies_without_the_checked_out_package(tmp_path: Path, finished_shards: int) -> None:
    """
    INVARIANT: completion is verified by the tooling the workflow pins, not the tested head's lock.

    A pull_request workflow runs main's YAML against the PR head's tree. A head whose lock predates
    `ci_esta.testing.evidence` fails `python -m ...evidence verify` with ModuleNotFoundError, so
    every stale PR went red on its next push. The action runs the verifier from its own checkout;
    this runs its exact `run:` text from a directory holding only shard artifacts.
    """
    action = yaml.safe_load(VERIFY_ACTION.read_text(encoding="utf-8"))
    (step,) = action["runs"]["steps"]
    for shard in range(1, finished_shards + 1):
        (tmp_path / f"junit-group-{shard}.xml").write_text("<testsuite/>")
        (tmp_path / f"pytest-status-group-{shard}").write_bytes(b"0\n")
    output = tmp_path / "github-output"
    result = subprocess.run(
        ["bash", "--noprofile", "--norc", "-eo", "pipefail", "-c", step["run"]],
        cwd=tmp_path,
        env={
            **os.environ,
            "GITHUB_ACTION_PATH": str(VERIFY_ACTION.parent),
            "GITHUB_OUTPUT": str(output),
            "PLAN_SHARD_COUNT": "2",
            "PLAN_MODE": "full",
        },
        capture_output=True,
        text=True,
    )
    complete = finished_shards == 2
    assert (result.returncode == 0) == complete, result.stderr
    assert (output.read_text() if output.exists() else "") == ("complete=true\n" if complete else "")


@pytest.mark.parametrize("missing", [False, True])
def test_completion_checks_every_global_shard_in_the_assigned_runner_range(tmp_path: Path, missing: bool) -> None:
    for shard in (3, 4):
        (tmp_path / f"junit-group-{shard}.xml").write_text("<testsuite/>")
        if shard != 4 or not missing:
            (tmp_path / f"pytest-status-group-{shard}").write_text("0")
    result = subprocess.run(
        ["bash", str(RECEIPT)],
        cwd=tmp_path,
        env={
            **os.environ,
            "PLAN_SHARD_COUNT": "4",
            "PLAN_MODE": "full",
            "PLAN_FIRST_SHARD": "3",
            "PLAN_LAST_SHARD": "4",
        },
        capture_output=True,
        text=True,
    )
    assert (result.returncode == 0) is (not missing)


@pytest.mark.parametrize("first,last", [("0", "1"), ("2", "1"), ("1", "5"), ("bad", "4")])
def test_completion_rejects_invalid_ranges(tmp_path: Path, first: str, last: str) -> None:
    result = subprocess.run(
        ["bash", str(RECEIPT)],
        cwd=tmp_path,
        env={
            **os.environ,
            "PLAN_SHARD_COUNT": "4",
            "PLAN_MODE": "full",
            "PLAN_FIRST_SHARD": first,
            "PLAN_LAST_SHARD": last,
        },
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
