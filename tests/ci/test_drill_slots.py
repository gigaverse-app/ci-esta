"""Exercise slot snapshots with real Git; only the GitHub transport is replaced."""

import re
import subprocess
from itertools import chain, repeat
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import yaml

from ci_esta import drill


class GitRepository:
    def __init__(self, path: Path):
        self.path = path
        path.mkdir()
        self.git("init", "-q")
        self.git("config", "user.email", "drill@example.invalid")
        self.git("config", "user.name", "Drill test")
        (path / "base.txt").write_text("initial\n")
        self.git("add", ".")
        self.git("commit", "-qm", "initial")
        self.git("branch", "-M", "main")
        self.initial = self.git("rev-parse", "HEAD")

    def git(self, *args: str, input_text: str | None = None) -> str:
        return subprocess.check_output(["git", *args], cwd=self.path, input=input_text, text=True).strip()

    def commit(self, branch: str, filename: str, content: str) -> str:
        self.git("checkout", "-qB", branch)
        (self.path / filename).write_text(content)
        self.git("add", ".")
        self.git("commit", "-qm", filename)
        return self.git("rev-parse", "HEAD")

    def api(self, path: str, *fields: str, method: str = "GET") -> dict[str, Any]:
        assert method == "GET"
        if "/git/commits/" in path:
            sha = path.split("/git/commits/")[1]
            return {
                "sha": sha,
                "tree": {"sha": self.git("rev-parse", f"{sha}^{{tree}}")},
                "message": self.git("log", "-1", "--format=%B", sha),
            }
        if "/git/ref/heads/" in path:
            branch = path.split("/git/ref/heads/")[1]
            return {"object": {"sha": self.git("rev-parse", f"refs/heads/{branch}")}}
        raise AssertionError(path)

    def api_json(self, path: str, body: dict[str, object], method: str = "POST") -> dict[str, Any]:
        if path.endswith("/git/commits"):
            parents = body["parents"]
            assert isinstance(parents, list)
            args = ["commit-tree", str(body["tree"]), "-m", str(body["message"])]
            for parent in parents:
                args += ["-p", str(parent)]
            return {"sha": self.git(*args)}
        if path.endswith("/git/refs"):
            self.git("update-ref", str(body["ref"]), str(body["sha"]), "0" * 40)
            return {}
        if path.endswith("/merges"):
            base = self.git("rev-parse", str(body["base"]))
            head = str(body["head"])
            tree = self.git("merge-tree", "--write-tree", base, head).splitlines()[0]
            sha = self.git("commit-tree", tree, "-p", base, "-p", head, "-m", "merge")
            self.git("update-ref", f"refs/heads/{body['base']}", sha, base)
            return {"sha": sha, "tree": {"sha": tree}}
        raise AssertionError(path)

    def gh(self, *args: str, check: bool = True) -> str:
        assert args[:3] == ("api", "-X", "DELETE")
        self.git("update-ref", "-d", "refs/heads/" + args[3].split("refs/heads/")[1])
        return ""


@pytest.fixture
def git_api(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> GitRepository:
    repo = GitRepository(tmp_path / "git")
    monkeypatch.setattr(drill, "_api", repo.api)
    monkeypatch.setattr(drill, "_api_json", repo.api_json)
    monkeypatch.setattr(drill, "_gh", repo.gh)
    return repo


def test_slot_snapshot_isolates_old_evidence_without_losing_new_main_or_candidate(git_api: GitRepository) -> None:
    repo = git_api
    old_head = repo.commit("old", "old-only.txt", "discard this content\n")
    repo.git("checkout", "-q", repo.initial)
    candidate = repo.commit("candidate", "candidate.txt", "retain candidate change\n")
    repo.git("checkout", "-q", repo.initial)
    main = repo.commit("main", "new-main.txt", "retain concurrent main change\n")
    base, head = drill._slot_snapshot("test/repo", main, candidate, old_head, repo.initial, "nonce")

    # Every previous run is behind the new base; the existing evidence resolver rejects it.
    repo.git("merge-base", "--is-ancestor", old_head, base)
    repo.git("merge-base", "--is-ancestor", base, head)
    repo.git("merge-base", "--is-ancestor", old_head, head)
    assert repo.git("rev-parse", f"{base}^{{tree}}") == repo.git("rev-parse", f"{main}^{{tree}}")
    assert repo.git("diff", "--name-only", base, head) == "candidate.txt"
    assert repo.git("show", f"{head}:new-main.txt") == "retain concurrent main change"
    assert "old-only.txt" not in repo.git("ls-tree", "--name-only", head)
    assert not repo.git("for-each-ref", "refs/heads/ci-drill/prepare/")


def test_next_slot_session_has_a_new_receipt_base_even_for_identical_inputs(git_api: GitRepository) -> None:
    repo = git_api
    base1, head1 = drill._slot_snapshot("test/repo", repo.initial, repo.initial, repo.initial, repo.initial, "one")
    base2, head2 = drill._slot_snapshot("test/repo", repo.initial, repo.initial, head1, base1, "two")
    assert base1 != base2 and head1 != head2
    repo.git("merge-base", "--is-ancestor", head1, base2)
    assert repo.git("rev-parse", f"{head1}^{{tree}}") == repo.git("rev-parse", f"{head2}^{{tree}}")


def test_conflicting_source_does_not_leak_a_prepare_branch(git_api: GitRepository) -> None:
    repo = git_api
    source = repo.commit("candidate", "base.txt", "candidate\n")
    repo.git("checkout", "-q", repo.initial)
    main = repo.commit("main", "base.txt", "main\n")
    with pytest.raises(subprocess.CalledProcessError):
        drill._slot_snapshot("test/repo", main, source, repo.initial, repo.initial, "conflict")
    assert not repo.git("for-each-ref", "refs/heads/ci-drill/prepare/")


def test_previously_drilled_candidate_changes_are_not_lost(git_api: GitRepository) -> None:
    repo = git_api
    candidate = repo.commit("candidate", "candidate.txt", "keep me\n")
    base1, head1 = drill._slot_snapshot("test/repo", repo.initial, candidate, repo.initial, repo.initial, "one")
    base2, head2 = drill._slot_snapshot("test/repo", repo.initial, candidate, head1, base1, "two")
    assert repo.git("diff", "--name-only", base2, head2) == "candidate.txt"
    assert repo.git("show", f"{head2}:candidate.txt") == "keep me"


def test_pool_contention_fails_before_mutation_and_exception_releases_owner(git_api: GitRepository) -> None:
    repo = git_api
    with pytest.raises(ValueError, match="failure inside owner"):
        with drill._pool_lease():
            owner = repo.git("rev-parse", f"refs/heads/{drill.LEASE_REF}")
            with pytest.raises(RuntimeError, match="Cannot acquire"):
                with drill._pool_lease():
                    pytest.fail("two drivers entered the same pool")
            assert repo.git("rev-parse", f"refs/heads/{drill.LEASE_REF}") == owner
            raise ValueError("failure inside owner")
    assert not repo.git("for-each-ref", f"refs/heads/{drill.LEASE_REF}")


LEASE = f"refs/heads/{drill.LEASE_REF}"
HOLDER_RECORD = '{"session": "local-holder", "host": "workstation"}'


def _plant_holder_lease(repo: GitRepository) -> str:
    """Another driver's lease, as `_pool_lease` writes it."""
    holder = repo.git("commit-tree", f"{repo.initial}^{{tree}}", "-m", f"ci-drill pool lease\n{HOLDER_RECORD}")
    repo.git("update-ref", LEASE, holder, "0" * 40)
    return holder


def test_a_waiting_driver_enters_only_after_the_holder_releases(
    git_api: GitRepository, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = git_api
    holder = _plant_holder_lease(repo)
    pauses: list[float] = []

    def holder_finishes(seconds: float) -> None:
        assert repo.git("rev-parse", LEASE) == holder, "the waiter must not touch a held lease"
        pauses.append(seconds)
        repo.git("update-ref", "-d", LEASE, holder)

    monkeypatch.setattr(drill, "_pause", holder_finishes)
    with drill._pool_lease(wait_seconds=600):
        assert repo.git("rev-parse", LEASE) != holder
    assert pauses == [drill.POLL_SECONDS]
    assert not repo.git("for-each-ref", LEASE)
    assert f"held by {HOLDER_RECORD}" in capsys.readouterr().err


def test_a_waiting_driver_never_takes_over_an_unreleased_lease(
    git_api: GitRepository, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = git_api
    holder = _plant_holder_lease(repo)
    # Only polling advances the clock, so the budget buys an exact number of polls.
    elapsed: list[float] = []
    monkeypatch.setattr(drill, "time", SimpleNamespace(monotonic=lambda: sum(elapsed)))
    monkeypatch.setattr(drill, "_pause", elapsed.append)
    with pytest.raises(RuntimeError, match=f"held by {re.escape(HOLDER_RECORD)}"):
        with drill._pool_lease(wait_seconds=3 * drill.POLL_SECONDS):
            pytest.fail("entered a pool another driver still holds")
    assert elapsed == [drill.POLL_SECONDS] * 3
    assert repo.git("rev-parse", LEASE) == holder
    # A long wait logs the holder once, not once per poll.
    assert capsys.readouterr().err.count("Waiting for") == 1


def test_a_refusal_without_a_visible_lease_is_not_waited_out(
    git_api: GitRepository, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Auth or transport failures are not contention; waiting them out would only delay the error."""
    refused = subprocess.CalledProcessError(1, ["gh", "api"], stderr="HTTP 403: Resource not accessible")
    create_commit = git_api.api_json

    def refuse_ref_creation(path: str, body: dict[str, object], method: str = "POST") -> dict[str, Any]:
        if path.endswith("/git/refs"):
            raise refused
        return create_commit(path, body, method)

    monkeypatch.setattr(drill, "_api_json", refuse_ref_creation)
    monkeypatch.setattr(drill, "_pause", lambda seconds: pytest.fail("waited out a non-contention failure"))
    with pytest.raises(subprocess.CalledProcessError) as raised:
        with drill._pool_lease(wait_seconds=600):
            pytest.fail("entered without a lease")
    assert raised.value is refused


SESSION = drill.DrillSession(
    url="url", branch="slot", pr_base="base", head_sha="new", started_at="2026-09-24T12:00:00Z"
)
SLOT_PROFILE = drill.PROFILES["gigaverse-backend"]
# The observed race, gigaverse-ai 2026-09-26: two runs created in one second; concurrency cancelled the older.
CASUALTY = 36207188473
SURVIVOR = 36207189014
NEXT_RUN = 36207190000
VALIDATION_JOB = "Check Python types, migrations and workflow policy"
Jobs = list[dict[str, object]]
IDLE_CASUALTY_JOBS: Jobs = [
    {"name": SLOT_PROFILE.plan_job, "conclusion": "cancelled"},
    {"name": "guard_rerun", "conclusion": "skipped"},
    {"name": VALIDATION_JOB, "conclusion": "cancelled"},
]


def _run(run_id: int, **fields: object) -> dict[str, object]:
    """A first-attempt pull_request run of the session head, created during the session."""
    run: dict[str, object] = {
        "id": run_id,
        "head_sha": SESSION.head_sha,
        "created_at": "2026-09-24T12:01:00Z",
        "event": "pull_request",
        "run_attempt": 1,
        "status": "completed",
        "conclusion": "success",
    }
    return run | fields


CANCELLED = _run(CASUALTY, conclusion="cancelled")


def _collect(
    monkeypatch: pytest.MonkeyPatch,
    polls: list[list[dict[str, object]]],
    known: set[int],
    jobs: dict[int, Jobs] | None = None,
) -> dict[str, object]:
    """`_next_run` against one run listing per poll (the last repeats) and each run's jobs."""
    listings = chain(polls, repeat(polls[-1]))
    run_jobs = {CASUALTY: IDLE_CASUALTY_JOBS} if jobs is None else jobs

    def api(path: str, *fields: str, method: str = "GET") -> dict[str, object]:
        return {"jobs": run_jobs[int(path.split("/runs/", 1)[1].split("/", 1)[0])]}

    monkeypatch.setattr(drill, "_latest_runs", lambda *args: next(listings))
    monkeypatch.setattr(drill, "_pause", lambda seconds: None)
    monkeypatch.setattr(drill, "_api", api)
    return drill._next_run(SLOT_PROFILE, SESSION, known)


def test_old_head_and_rerun_attempt_cannot_satisfy_new_session(monkeypatch: pytest.MonkeyPatch) -> None:
    runs = [
        _run(24, head_sha="old"),
        _run(23, run_attempt=2),
        _run(22, event="workflow_dispatch"),
        _run(21, created_at="2026-09-23T12:01:00Z"),
        _run(20),
    ]
    assert _collect(monkeypatch, [runs], set())["id"] == 20


@pytest.mark.parametrize(
    "polls",
    [
        [[CANCELLED, _run(SURVIVOR)]],
        [[CANCELLED, _run(SURVIVOR, status="in_progress", conclusion=None)], [CANCELLED, _run(SURVIVOR)]],
    ],
    ids=["sibling-finished", "sibling-still-running"],
)
def test_a_run_cancelled_in_favour_of_a_sibling_is_never_the_measured_run(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], polls: list[list[dict[str, object]]]
) -> None:
    """INVARIANT: concurrency cancelling one of two same-second runs measures the survivor, not the casualty."""
    assert _collect(monkeypatch, polls, set())["id"] == SURVIVOR
    assert f"run {CASUALTY} was cancelled in favour of sibling {SURVIVOR}" in capsys.readouterr().err


def test_a_superseded_run_cannot_stand_in_for_the_next_scenario(monkeypatch: pytest.MonkeyPatch) -> None:
    """INVARIANT: once its sibling is measured, a cancelled casualty is spent, not an answer for the next action."""
    known: set[int] = set()
    both = [CANCELLED, _run(SURVIVOR)]
    assert _collect(monkeypatch, [both], known)["id"] == SURVIVOR
    assert _collect(monkeypatch, [both, [*both, _run(NEXT_RUN)]], known)["id"] == NEXT_RUN


def test_a_cancelled_run_without_a_surviving_sibling_is_still_measured(monkeypatch: pytest.MonkeyPatch) -> None:
    """INVARIANT: only a sibling excuses a cancellation; a lone cancelled run is scored and fails."""
    assert _collect(monkeypatch, [[CANCELLED]], set())["conclusion"] == "cancelled"


@pytest.mark.parametrize("conclusion", ["success", "failure"])
def test_a_casualty_that_already_validated_fails_loudly_instead_of_hiding_its_repeat(
    monkeypatch: pytest.MonkeyPatch, conclusion: str
) -> None:
    """INVARIANT: skipping a casualty never hides work the scorer would count as repeated."""
    worked: Jobs = [*IDLE_CASUALTY_JOBS[:2], {"name": VALIDATION_JOB, "conclusion": conclusion}]
    with pytest.raises(
        RuntimeError, match=f"Run {CASUALTY} was cancelled in favour of {SURVIVOR} after .*{VALIDATION_JOB}"
    ):
        _collect(monkeypatch, [[CANCELLED, _run(SURVIVOR)]], set(), jobs={CASUALTY: worked})


def test_a_casualty_whose_only_finished_job_always_runs_is_still_idle(monkeypatch: pytest.MonkeyPatch) -> None:
    """INVARIANT: always-run jobs validate nothing, so they do not make a casualty count as work."""
    jobs: dict[int, Jobs] = {CASUALTY: [{"name": "guard_rerun", "conclusion": "success"}]}
    assert _collect(monkeypatch, [[CANCELLED, _run(SURVIVOR)]], set(), jobs=jobs)["id"] == SURVIVOR


def test_green_run_without_a_successful_planner_is_not_proof(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        drill, "_api", lambda *args, **kwargs: {"jobs": [{"name": "guard_rerun", "conclusion": "success"}]}
    )
    with pytest.raises(RuntimeError, match="did not successfully execute"):
        drill._outcome(drill.PROFILES["gigaverse-backend"], "first run", {"id": 42})


def test_signal_stop_interrupts_wait_before_another_scenario() -> None:
    drill.STOP.set()
    try:
        with pytest.raises(RuntimeError, match="interrupted"):
            drill._pause(100)
    finally:
        drill.STOP.clear()


class SlotGitHub(GitRepository):
    """Real Git plus GitHub's closed-head and stale-base rules found by live probes."""

    def __init__(self, path: Path):
        super().__init__(path)
        self.branch = "ci-drill/head"
        self.base_branch = "ci-drill/base"
        self.git("branch", self.base_branch, self.initial)
        self.head = self.commit(self.branch, "old.txt", "old session")
        self.base = self.initial
        self.state = "closed"
        self.draft = False
        self.body = "scripts/ci/ci_drill.py"
        self.fail_probe = False

    def pr(self) -> dict[str, Any]:
        return {
            "state": self.state,
            "merged": False,
            "draft": self.draft,
            "head": {"ref": self.branch, "sha": self.head, "repo": {"full_name": "gigaverse-app/gigaverse-backend"}},
            "base": {
                "ref": self.base_branch,
                "sha": self.base,
                "repo": {"full_name": "gigaverse-app/gigaverse-backend"},
            },
            "body": self.body,
            "html_url": "https://github.com/gigaverse-app/gigaverse-backend/pull/5053",
        }

    def api(self, path: str, *fields: str, method: str = "GET") -> dict[str, Any]:
        if "/pulls/" in path:
            return self.pr()
        if "/actions/workflows/" in path:
            return {"workflow_runs": []}
        if "/contents/" in path:
            import base64

            file_path, ref = path.split("/contents/")[1].split("?ref=")
            return {
                "content": base64.b64encode((self.git("show", f"{ref}:{file_path}") + "\n").encode()).decode(),
                "sha": self.git("rev-parse", f"{ref}:{file_path}"),
            }
        return super().api(path, *fields, method=method)

    def api_json(self, path: str, body: dict[str, object], method: str = "POST") -> dict[str, Any]:
        if "/pulls/" in path:
            if "base" in body:
                assert self.state == "open", "GitHub cannot retarget a closed PR"
                self.base_branch = str(body["base"])
                self.base = self.git("rev-parse", self.base_branch)
            if "body" in body:
                self.body = str(body["body"])
            return self.pr()
        if "/git/refs/heads/" in path and method == "PATCH":
            branch = path.split("/git/refs/heads/")[1]
            current = self.git("rev-parse", "--verify", f"refs/heads/{branch}")
            assert body["force"] is False
            self.git("merge-base", "--is-ancestor", current, str(body["sha"]))
            self.git("update-ref", f"refs/heads/{branch}", str(body["sha"]), current)
            # GitHub keeps the recorded head frozen while closed and the base until retarget.
            if branch == self.branch and self.state == "open":
                self.head = str(body["sha"])
            return {}
        return super().api_json(path, body, method)

    def gh(self, *args: str, check: bool = True, stdin: str | None = None) -> str:
        import base64
        import json

        if args[:3] == ("api", "-X", "PUT"):
            if self.fail_probe:
                raise RuntimeError("injected probe failure")
            assert stdin is not None
            body = json.loads(stdin)
            assert body["branch"] == self.branch
            parent = self.git("rev-parse", self.branch)
            self.git("checkout", "-q", self.branch)
            self.git("reset", "--hard", self.branch)
            (self.path / "base.txt").write_bytes(base64.b64decode(body["content"]))
            self.git("add", ".")
            self.git("commit", "-qm", "probe")
            self.head = self.git("rev-parse", self.branch)
            self.git("merge-base", "--is-ancestor", parent, self.head)
            return json.dumps({"commit": {"sha": self.head}})
        if args[:2] == ("pr", "reopen"):
            result = subprocess.run(["git", "merge-base", "--is-ancestor", self.head, self.base_branch], cwd=self.path)
            assert result.returncode == 1, "GitHub refuses already-merged closed heads"
            self.state = "open"
            self.head = self.git("rev-parse", self.branch)
            return ""
        if args[:2] == ("pr", "ready"):
            assert self.state == "open"
            self.draft = "--undo" in args
            return ""
        if args[:2] == ("pr", "close"):
            self.state = "closed"
            return ""
        if args[:2] == ("pr", "view"):
            return json.dumps({"state": self.state.upper(), "isDraft": self.draft})
        return super().gh(*args, check=check)


@pytest.fixture
def slot_github(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> SlotGitHub:
    repo = SlotGitHub(tmp_path / "github")
    monkeypatch.setattr(drill, "_api", repo.api)
    monkeypatch.setattr(drill, "_api_json", repo.api_json)
    monkeypatch.setattr(drill, "_gh", repo.gh)
    return repo


def test_three_sessions_reuse_one_pr_with_fresh_base_and_only_probe_diff(slot_github: SlotGitHub) -> None:
    repo = slot_github
    profile = drill.PROFILES["gigaverse-backend"].model_copy(update={"touch_path": "base.txt"})
    heads = [repo.head]
    bases: list[str] = []
    for _ in range(3):
        with drill._drill_session(profile, "main", "retrigger", False) as session:
            assert session.url.endswith("/5053")
            bases.append(session.pr_base)
            assert repo.git("diff", "--name-only", repo.base, repo.head) == "base.txt"
            for old in heads:
                repo.git("merge-base", "--is-ancestor", old, repo.base)
            assert repo.base == repo.git("rev-parse", session.pr_base)
            heads.append(repo.head)
        assert repo.state == "closed" and repo.draft
        assert repo.git("rev-parse", repo.branch) == heads[-1]
    assert len(set(heads)) == 4
    assert bases[0] == bases[2] and bases[0] != bases[1]


def test_failure_after_reopen_leaves_slot_closed_and_next_session_can_recover(slot_github: SlotGitHub) -> None:
    repo = slot_github
    profile = drill.PROFILES["gigaverse-backend"].model_copy(update={"touch_path": "base.txt"})
    repo.fail_probe = True
    with pytest.raises(RuntimeError, match="injected probe failure"):
        with drill._drill_session(profile, "main", "retrigger", False):
            pytest.fail("probe should have failed")
    assert repo.state == "closed" and repo.draft
    repo.fail_probe = False
    with drill._drill_session(profile, "main", "retrigger", False):
        assert repo.git("diff", "--name-only", repo.base, repo.head) == "base.txt"


def test_main_only_probe_cannot_pass_a_red_main_moved_run() -> None:
    card = drill.MainMovedCard(
        consumer="backend",
        base="main",
        runs=(drill.RunOutcome(label="moved", run_id=1, jobs=(), conclusion="failure"),),
    )
    assert not drill.met("pass", [], [], moved=[card])


def test_probe_changes_python_ast_so_semantic_selection_cannot_ignore_it(slot_github: SlotGitHub) -> None:
    import ast

    repo = slot_github
    profile = drill.PROFILES["gigaverse-backend"].model_copy(update={"touch_path": "base.txt"})
    # Use a valid Python module; the original fixture's initial text is a bare name.
    with drill._drill_session(profile, "main", "retrigger", False) as session:
        before = repo.git("show", f"{repo.base}:base.txt")
        after = repo.git("show", f"{session.head_sha}:base.txt")
        assert ast.dump(ast.parse(before)) != ast.dump(ast.parse(after))


def test_first_run_with_zero_selected_tests_is_not_drill_proof(monkeypatch: pytest.MonkeyPatch) -> None:
    profile = drill.PROFILES["gigaverse-backend"]
    monkeypatch.setattr(
        drill, "_api", lambda *args, **kwargs: {"jobs": [{"id": 1, "name": profile.plan_job, "conclusion": "success"}]}
    )
    monkeypatch.setattr(drill, "_gh", lambda *args, **kwargs: "Test impact: 0/100 files; none")
    with pytest.raises(RuntimeError, match="selected no tests"):
        drill._outcome(profile, "first run", {"id": 42, "conclusion": "success"})


def test_non_fast_forward_slot_update_fails_without_replacing_ref(slot_github: SlotGitHub) -> None:
    repo = slot_github
    original = repo.git("rev-parse", repo.branch)
    with pytest.raises(subprocess.CalledProcessError):
        drill._slot_ref("test/repo", repo.branch, repo.initial)
    assert repo.git("rev-parse", repo.branch) == original


def test_lease_cleanup_does_not_delete_a_different_owner(git_api: GitRepository) -> None:
    repo = git_api
    replacement = ""
    with pytest.raises(RuntimeError, match="ownership changed"):
        with drill._pool_lease():
            ref = f"refs/heads/{drill.LEASE_REF}"
            owner = repo.git("rev-parse", ref)
            replacement = repo.git("commit-tree", f"{owner}^{{tree}}", "-p", owner, "-m", "replacement owner")
            repo.git("update-ref", ref, replacement, owner)
    assert repo.git("rev-parse", f"refs/heads/{drill.LEASE_REF}") == replacement


def test_failure_between_head_update_and_reopen_is_retryable(
    slot_github: SlotGitHub, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = slot_github
    transport = repo.gh

    def fail_reopen(*args: str, **kwargs: Any) -> str:
        if args[:2] == ("pr", "reopen"):
            raise RuntimeError("lost connection before reopen")
        return transport(*args, **kwargs)

    monkeypatch.setattr(drill, "_gh", fail_reopen)
    profile = drill.PROFILES["gigaverse-backend"].model_copy(update={"touch_path": "base.txt"})
    with pytest.raises(RuntimeError, match="lost connection"):
        with drill._drill_session(profile, "main", "retrigger", False):
            pytest.fail("reopen should have failed")
    assert repo.state == "closed"
    unpublished_head = repo.git("rev-parse", repo.branch)
    monkeypatch.setattr(drill, "_gh", transport)
    with drill._drill_session(profile, "main", "retrigger", False) as session:
        repo.git("merge-base", "--is-ancestor", unpublished_head, session.head_sha)


def test_selected_but_skipped_pytest_is_not_initial_drill_proof(monkeypatch: pytest.MonkeyPatch) -> None:
    profile = drill.PROFILES["gigaverse-backend"]
    monkeypatch.setattr(
        drill,
        "_api",
        lambda *args, **kwargs: {
            "jobs": [
                {"id": 1, "name": profile.plan_job, "conclusion": "success"},
                {"id": 2, "name": "Test unit behavior · 1 concurrent shards", "conclusion": "skipped"},
            ]
        },
    )
    monkeypatch.setattr(drill, "_gh", lambda *args, **kwargs: "Test impact: 1/100 files; selected")
    with pytest.raises(RuntimeError, match="did not execute pytest"):
        drill._outcome(profile, "first run", {"id": 42, "conclusion": "success"})


def test_history_heavy_full_report_stays_below_comment_limit_without_losing_proof() -> None:
    history = tuple(f"Candidate run {i} rejected: {'old receipt ' * 30}" for i in range(200))
    proof = "Validated evidence candidate current-session from run 987 for incremental PR selection."
    cards = []
    for profile in drill.PROFILES.values():
        for base in ("main", "candidate"):
            for family in ("retrigger", "retag"):
                runs = [
                    drill.RunOutcome(label=f"scenario {i}", run_id=100 + i, jobs=(), resolver_lines=(*history, proof))
                    for i in range(3)
                ]
                cards.append(drill.score(profile, base, "head", runs, family=family))
    body = drill.report(223, cards, [])
    assert len(body) < 60_000
    assert proof in body
    assert "https://github.com/gigaverse-app/gigaverse-backend/actions/runs/100" in body
    assert cards[0].runs[0].resolver_lines == (*history, proof), "formatting must not discard underlying evidence"


@pytest.mark.parametrize(
    "events,expected",
    [
        ("pull_request", False),
        ("{pull_request: {}}", False),
        ("{pull_request: {types: [opened, synchronize]}}", False),
        ("{pull_request: {types: [ready_for_review]}}", True),
    ],
)
def test_ready_drill_reads_candidate_trigger(events: str, expected: bool) -> None:
    assert drill.readiness_triggers_validation(f"on: {events}") is expected


@pytest.mark.parametrize("unexpected", [False, True])
def test_zero_run_probe_rejects_even_cancelled_ready_runs(monkeypatch: pytest.MonkeyPatch, unexpected: bool) -> None:
    monkeypatch.setattr(drill, "_pause", lambda _: None)
    run = {"id": 12, "head_sha": SESSION.head_sha, "created_at": SESSION.started_at, "conclusion": "cancelled"}
    monkeypatch.setattr(drill, "_latest_runs", lambda *_: [run])
    if unexpected:
        with pytest.raises(RuntimeError, match="Ready allocated"):
            drill._assert_no_ready_run(SLOT_PROFILE, SESSION, set())
    else:
        drill._assert_no_ready_run(SLOT_PROFILE, SESSION, {12})


def test_the_hosted_drill_sets_its_lease_wait_through_the_environment() -> None:
    """
    The job runs the default branch's script with the PR's workflow, so a new flag on argv breaks
    every drill dispatched before the flag merges (run 37429860753). The budget travels as an env var.
    """
    workflow = yaml.safe_load((Path(__file__).resolve().parents[2] / "examples/gigaverse-ci-drill.yaml").read_text())
    (step,) = [step for step in workflow["jobs"]["drill"]["steps"] if "ci_drill" in str(step.get("run", ""))]
    assert float(step["env"][drill.LEASE_WAIT_ENV]) > 0
    assert "--lease-wait" not in step["run"]
