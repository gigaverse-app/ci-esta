"""Receipts from a checkout must match API receipts without spending core quota."""

import base64
import json
import os
import subprocess
import zlib
from pathlib import Path
from typing import TypedDict, cast

import pytest

ROOT = Path(__file__).resolve().parents[2]


class ObjectFixture(TypedDict):
    objects: dict[str, object]
    merge: str
    head: str
    base: str


class IdentityResult(TypedDict):
    tested: str
    inventory: str
    calls: list[str]


def git(repo: Path, *args: str) -> bytes:
    return subprocess.check_output(["git", "-C", str(repo), *args], stderr=subprocess.PIPE)


@pytest.fixture
def history(tmp_path: Path) -> tuple[Path, ObjectFixture]:
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-b", "main")
    git(repo, "config", "user.name", "Fixture")
    git(repo, "config", "user.email", "fixture@example.test")
    git(repo, "config", "core.autocrlf", "false")
    (repo / ".github").mkdir()
    (repo / ".github" / "scan.yaml").write_text("scan: everything\n")
    (repo / "app.py").write_text("print('first')\n")
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "base")
    base = git(repo, "rev-parse", "HEAD").decode().strip()
    # A real content-addressed dependency commit reused by both snapshots.
    dependency = base
    (repo / "uv.lock").write_text(f'git = "https://github.com/gigaverse-app/backend-common.git?rev=v1#{dependency}"\n')
    (repo / "pyproject.toml").write_text('backend-common = {git = "https://github.com/gigaverse-app/backend-common.git", rev = "v1"}\n')
    (repo / ".github" / "backend-common-bump.json").write_text(json.dumps({"commit": dependency}))
    (repo / "unicode-é file").write_text("preserve paths")
    git(repo, "add", ".")
    git(repo, "update-index", "--add", "--cacheinfo", f"160000,{dependency},vendored")
    git(repo, "update-index", "--chmod=+x", "app.py")
    git(repo, "commit", "-qm", "head")
    head = git(repo, "rev-parse", "HEAD").decode().strip()
    tree = git(repo, "rev-parse", "HEAD^{tree}").decode().strip()
    merge = git(repo, "commit-tree", tree, "-p", base, "-p", head, "-m", "test merge").decode().strip()
    git(repo, "update-ref", "refs/heads/merge", merge)
    objects: dict[str, object] = {}
    for line in git(repo, "rev-list", "--objects", "--all").decode().splitlines():
        sha = line.split()[0]
        kind = git(repo, "cat-file", "-t", sha).decode().strip()
        raw = git(repo, "cat-file", kind, sha)
        if kind == "commit":
            headers = raw.decode().split("\n\n", 1)[0].splitlines()
            objects[sha] = {"tree": {"sha": headers[0].split()[1]}, "parents": [
                {"sha": h.split()[1]} for h in headers if h.startswith("parent ")
            ]}
        elif kind == "tree":
            entries = []
            for entry in git(repo, "ls-tree", "-z", sha).split(b"\0"):
                if entry:
                    metadata, name = entry.split(b"\t", 1)
                    mode, entry_type, oid = metadata.decode().split()
                    entries.append({"mode": mode, "type": entry_type, "sha": oid, "path": name.decode()})
            objects[sha] = {"tree": entries, "truncated": False}
        elif kind == "blob":
            objects[sha] = {"content": base64.b64encode(raw).decode(), "encoding": "base64"}
    fixture: ObjectFixture = {"objects": objects, "merge": merge, "head": head, "base": base}
    return repo, fixture


def identities(repo: Path | None, fixture: ObjectFixture) -> IdentityResult:
    script = r"""
const {strictGithub} = require(process.argv[1] + '/tests/ci/github_rest_fake.cjs');
const {testedIdentity,inventoryIdentity} = require(process.argv[1] + '/actions/resolve-lane-evidence/inputs.cjs');
const input=JSON.parse(process.env.OBJECT_FIXTURE), calls=[];
const read=async (kind,sha)=>{calls.push(`${kind}:${sha}`);return {data:input.objects[sha]};};
const client=strictGithub({git:{
  getCommit:({commit_sha})=>read('commit',commit_sha),
  getTree:({tree_sha})=>read('tree',tree_sha),
  getBlob:({file_sha})=>read('blob',file_sha),
}});
(async()=>{
 const tested=await testedIdentity(client,client,{owner:'o',repo:'r'},input.merge,{warning:()=>{}});
 const inventory=await inventoryIdentity(client,client,{owner:'o',repo:'r'},input.head,
   ['uv.lock','pyproject.toml','.github/scan.yaml','unicode-é file','vendored','app.py','absent']);
 console.log(JSON.stringify({tested,inventory,calls}));
})().catch(e=>{console.error(e);process.exitCode=1;});
"""
    result = subprocess.run(
        ["node", "-e", script, ROOT.as_posix()], capture_output=True, text=True, encoding="utf-8",
        env={**os.environ, "GITHUB_WORKSPACE": str(repo) if repo else "", "OBJECT_FIXTURE": json.dumps(fixture)},
    )
    assert result.returncode == 0, result.stderr
    return cast(IdentityResult, json.loads(result.stdout))


def test_checkout_receipts_match_api_without_any_git_api_reads(history: tuple[Path, ObjectFixture]) -> None:
    repo, fixture = history
    remote = identities(None, fixture)
    # Uncommitted content and replacement refs must never change immutable evidence.
    (repo / "uv.lock").write_text("dirty checkout")
    git(repo, "replace", fixture["head"], fixture["base"])
    local = identities(repo, fixture)
    assert local["tested"] == remote["tested"]
    assert local["inventory"] == remote["inventory"]
    assert len(remote["calls"]) >= 12  # The ordinary normalized lane + security inventory cost.
    assert local["calls"] == []


def test_shallow_checkout_falls_back_only_for_missing_objects(history: tuple[Path, ObjectFixture], tmp_path: Path) -> None:
    repo, fixture = history
    remote = identities(None, fixture)
    shallow = tmp_path / "shallow"
    subprocess.run(["git", "clone", "--depth=1", "--branch=main", repo.as_uri(), str(shallow)], check=True, capture_output=True)
    # Both absent commits exist remotely. Even a promisor checkout must fall
    # back to the API instead of silently fetching its missing history.
    git(shallow, "config", "remote.origin.promisor", "true")
    local = identities(shallow, fixture)
    assert local["tested"] == remote["tested"]
    assert local["inventory"] == remote["inventory"]
    assert 0 < len(local["calls"]) < len(remote["calls"])
    assert f'commit:{fixture["merge"]}' in local["calls"]
    assert not any(call.startswith(("tree:", "blob:")) for call in local["calls"])


def test_absent_checkout_retains_api_behavior(history: tuple[Path, ObjectFixture], tmp_path: Path) -> None:
    _, fixture = history
    local = identities(tmp_path / "absent", fixture)
    remote = identities(None, fixture)
    assert local["tested"] == remote["tested"]
    assert local["inventory"] == remote["inventory"]
    assert sorted(local["calls"]) == sorted(remote["calls"])


def test_corrupt_local_content_cannot_issue_a_different_receipt(history: tuple[Path, ObjectFixture]) -> None:
    repo, fixture = history
    remote = identities(None, fixture)
    sha = git(repo, "rev-parse", "HEAD:uv.lock").decode().strip()
    loose = repo / ".git" / "objects" / sha[:2] / sha[2:]
    loose.chmod(0o600)
    loose.write_bytes(zlib.compress(b"blob 4\0evil"))
    local = identities(repo, fixture)
    assert local["tested"] == remote["tested"]
    assert local["inventory"] == remote["inventory"]
    assert local["calls"] == [f"blob:{sha}", f"blob:{sha}"]
