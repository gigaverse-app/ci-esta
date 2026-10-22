"""A receipt identifies the tested consumer tree and actual shared implementation."""

import hashlib
import itertools
import json
import os
import subprocess
from collections.abc import Mapping
from pathlib import Path

import pytest
import yaml

RECEIPT = Path(__file__).resolve().parents[2] / ".github/actions/resolve-lane-evidence/inputs.cjs"


def receipt(root: Path, sha: str = "merge-a") -> str:
    result = subprocess.run(
        [
            "node",
            "-e",
            "const {validationReceipt}=require(process.argv[1]); console.log(validationReceipt(process.argv[2],process.argv[3]));",
            str(RECEIPT),
            str(root / ".github/actions/resolve-lane-evidence"),
            sha,
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


@pytest.mark.parametrize("changed", ["merge", "action", "workflow", "script", "source", "delete"])
def test_changed_execution_inputs_invalidate_the_receipt(tmp_path: Path, changed: str) -> None:
    files = {
        "action": tmp_path / ".github/actions/resolve-lane-evidence/action.yml",
        "workflow": tmp_path / ".github/workflows/check.yaml",
        "script": tmp_path / "scripts/check.py",
        "source": tmp_path / "src/ci_esta/check.py",
    }
    for file in files.values():
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text("original")
    before = receipt(tmp_path)
    assert receipt(tmp_path) == before
    if changed == "delete":
        files["source"].unlink()
    elif changed != "merge":
        files[changed].write_text("different")
    assert receipt(tmp_path, "merge-b" if changed == "merge" else "merge-a") != before


ACTION = RECEIPT.parent / "action.yml"
STRICT_FAKE = RECEIPT.parents[3] / "tests/ci/github_rest_fake.cjs"
TREE = "7e598c9ab0000000000000000000000000000000"
OTHER_TREE = "1111111111111111111111111111111111111111"
BASE = "a0f071b160000000000000000000000000000000"
HEAD = "eaf32c3e20000000000000000000000000000000"
OTHER_HEAD = "2222222222222222222222222222222222222222"
# gigaverse-backend#4957: GitHub re-created the merge for one head as 3124bdb and cb1a420,
# one second apart, with the same tree and parents.
# Each call is a separate run, so receipts are compared across runs as they are in CI.
RUN_IDS = itertools.count(1000)
MERGE = "3124bdbb7fa4bb404710ace233f9644fd9166568"
RECREATED_MERGE = "cb1a42000fc50123ef32550a4f8dcefdc143b711"


def action_receipt(
    merges: Mapping[str, Mapping[str, object] | None],
    sha: str,
    repository: "Repository | None" = None,
    *,
    token: str = "",
    inventory_paths: tuple[str, ...] = (),
    lane_input_paths: tuple[str, ...] = (),
) -> tuple[str, list[str]]:
    """
    Run the action's real script with strict clients; a None commit makes git.getCommit fail.

    `repository` serves the consumer's trees and blobs and, through getOctokit, the pinned
    backend-common commits' trees, which only the dependency token can read.
    """
    script = yaml.safe_load(ACTION.read_text(encoding="utf-8"))["runs"]["steps"][0]["with"]["script"]
    if inventory_paths:
        script = """
const { inventoryIdentity, validationReceipt } = require(`${process.env.GITHUB_ACTION_PATH}/inputs.cjs`);
const shared = process.env.DEPENDENCY_TOKEN ? getOctokit(process.env.DEPENDENCY_TOKEN) : null;
const identity = await inventoryIdentity(github, shared, context.repo, process.env.TESTED_MERGE_SHA,
    JSON.parse(process.env.INVENTORY_PATHS));
core.setOutput('receipt', validationReceipt(process.env.GITHUB_ACTION_PATH, identity));
"""
    harness = r"""
const input = JSON.parse(process.env.RECEIPT_TEST);
const { strictGithub } = require(process.env.GITHUB_REST_FAKE);
const outputs = {}, warnings = [];
const commits = { ...input.heads, ...input.merges };
const github = strictGithub({ git: {
  getCommit: async ({ commit_sha }) => {
    const commit = commits[commit_sha];
    if (!commit) throw new Error(`no commit ${commit_sha}`);
    return { data: commit };
  },
  getTree: async ({ tree_sha }) => {
    const tree = input.trees[tree_sha];
    if (!tree) throw new Error(`no tree ${tree_sha}`);
    return { data: { sha: tree_sha, tree, truncated: false } };
  },
  getBlob: async ({ file_sha }) => {
    const text = input.blobs[file_sha];
    if (text === undefined) throw new Error(`no blob ${file_sha}`);
    return { data: { content: Buffer.from(text).toString("base64"), encoding: "base64" } };
  },
} });
const getOctokit = (token) => {
  if (token !== "dependency-token") throw new Error("wrong token");
  return strictGithub({ git: { getCommit: async ({ owner, repo, commit_sha }) => {
    const tree = owner === "gigaverse-app" && repo === "backend-common" && input.shared[commit_sha];
    if (!tree) throw new Error(`no shared commit ${commit_sha}`);
    return { data: { tree: { sha: tree } } };
  } } });
};
const core = { setOutput: (k, v) => outputs[k] = v, warning: (m) => warnings.push(m), info: () => {} };
const context = { eventName: "push", runId: input.runId, repo: { owner: "o", repo: "r" }, payload: {} };
const AsyncFunction = Object.getPrototypeOf(async function () {}).constructor;
new AsyncFunction("github", "context", "core", "require", "process", "getOctokit", input.script)(
  github, context, core, require, process, getOctokit,
).then(() => console.log(JSON.stringify({ receipt: outputs.receipt, warnings })));
"""
    served = repository or Repository()
    result = subprocess.run(
        ["node", "-e", harness],
        check=True,
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "RECEIPT_TEST": json.dumps(
                {
                    "script": script,
                    "merges": merges,
                    "heads": served.heads,
                    "trees": served.trees,
                    "blobs": served.blobs,
                    "shared": served.shared,
                    "runId": next(RUN_IDS),
                }
            ),
            "GITHUB_REST_FAKE": str(STRICT_FAKE),
            "GITHUB_ACTION_PATH": str(ACTION.parent),
            "TESTED_MERGE_SHA": sha,
            "EVIDENCE_LANES": "{}",
            "INVENTORY_PATHS": json.dumps(inventory_paths),
            "EVIDENCE_INPUT_PATHS": json.dumps(lane_input_paths),
            "DEPENDENCY_TOKEN": token,
        },
    )
    parsed = json.loads(result.stdout)
    return parsed["receipt"], parsed["warnings"]


def test_lane_receipt_reuses_only_identical_declared_inputs() -> None:
    repository = Repository()

    def identity(package: str, application: str, workflow: str = "run all contracts") -> str:
        tree = repository.tree(
            {
                "libraries": "tree:" + repository.tree({"due.py": package}),
                "contracts.yaml": workflow,
                "app.py": application,
            }
        )
        merges = {MERGE: {"tree": {"sha": tree}, "parents": [{"sha": BASE}, {"sha": HEAD}]}}
        return action_receipt(merges, MERGE, repository, lane_input_paths=("libraries", "contracts.yaml"))[0]

    original = identity("package v1", "app v1")
    assert identity("package v1", "app v2") == original
    assert identity("package v2", "app v1") != original
    assert identity("package v1", "app v1", "changed execution") != original


class Repository:
    """Git objects for fake consumer trees, addressed by content like the real ones."""

    def __init__(self) -> None:
        self.trees: dict[str, list[dict[str, str]]] = {}
        self.blobs: dict[str, str] = {}
        self.heads: dict[str, dict[str, object]] = {
            HEAD: {"tree": {"sha": "3" * 40}, "parents": []},
            OTHER_HEAD: {"tree": {"sha": "4" * 40}, "parents": []},
        }
        self.shared: dict[str, str] = {}

    def blob(self, text: str) -> str:
        sha = hashlib.sha1(text.encode()).hexdigest()
        self.blobs[sha] = text
        return sha

    def tree(self, entries: dict[str, str]) -> str:
        """entries: path -> blob text, or path -> tree sha for a `tree:` prefixed value."""
        listing = []
        for name, value in sorted(entries.items()):
            if value.startswith("tree:"):
                listing.append({"path": name, "mode": "040000", "type": "tree", "sha": value[5:]})
            else:
                listing.append({"path": name, "mode": "100644", "type": "blob", "sha": self.blob(value)})
        sha = hashlib.sha1(json.dumps(listing).encode()).hexdigest()
        self.trees[sha] = listing
        return sha

    def consumer(self, rev: str, commit: str, app: str = "VALUE = 1") -> str:
        """A consumer tree pinning backend-common at `rev`, resolved by the lock to `commit`."""
        github = self.tree(
            {
                "backend-common-bump.json": json.dumps({"sha": commit, "runtime_changed": True}, indent=2),
                "workflows": "tree:" + self.tree({"test.yaml": "on: pull_request"}),
            }
        )
        url = "https://github.com/gigaverse-app/backend-common.git"
        return self.tree(
            {
                ".github": f"tree:{github}",
                "pyproject.toml": f'[tool.uv.sources]\ngigaverse-backend-common = {{ git = "{url}", rev = "{rev}" }}\n',
                "uv.lock": (
                    f'requires-dist = [{{ name = "gigaverse-backend-common", git = "{url}?rev={rev}" }}]\n'
                    f'source = {{ git = "{url}?rev={rev}#{commit}" }}\n'
                ),
                "src/app.py": app,
            }
        )

    def head(self, sha: str, tree: str) -> str:
        self.heads[sha] = {"tree": {"sha": tree}, "parents": [{"sha": BASE}]}
        return sha


def merge(tree: str = TREE, parents: tuple[str, ...] = (BASE, HEAD)) -> dict[str, object]:
    return {"tree": {"sha": tree}, "parents": [{"sha": parent} for parent in parents]}


def test_a_recreated_merge_of_the_same_tree_keeps_its_receipt() -> None:
    """INVARIANT: the receipt names what was tested (tree and parents), not the merge commit's SHA."""
    merges = {MERGE: merge(), RECREATED_MERGE: merge()}

    assert action_receipt(merges, MERGE)[0] == action_receipt(merges, RECREATED_MERGE)[0]


@pytest.mark.parametrize(
    "changed",
    [merge(tree=OTHER_TREE), merge(parents=(BASE, OTHER_HEAD)), merge(parents=(HEAD, BASE))],
    ids=["tree", "parent", "parent-order"],
)
def test_a_different_tested_merge_changes_the_receipt(changed: dict[str, object]) -> None:
    """CONTROL: any change to the tested tree, the base or the head's tree still invalidates the receipt."""
    merges = {MERGE: merge(), RECREATED_MERGE: changed}

    assert action_receipt(merges, MERGE)[0] != action_receipt(merges, RECREATED_MERGE)[0]


def test_an_unreadable_merge_falls_back_to_its_exact_commit() -> None:
    """A SHA pins the tree and parents, so the fallback stays sound: it matches only that commit."""
    unreadable = {MERGE: None, RECREATED_MERGE: None}
    readable = {MERGE: merge(), RECREATED_MERGE: merge()}

    receipt_a, warnings = action_receipt(unreadable, MERGE)

    assert receipt_a == action_receipt(unreadable, MERGE)[0]
    assert receipt_a != action_receipt(unreadable, RECREATED_MERGE)[0]
    assert receipt_a != action_receipt(readable, MERGE)[0]
    assert any("only runs of this exact merge commit can be reused" in warning for warning in warnings)


PR_COMMIT = "6e48180ffd223644e678cdb88c65418570e42cc7"
TAG_COMMIT = "0d34ec37f755980e25edd3be4c993dc0e605a6d1"
SHARED_TREE = "ba3aca10f9581e4cb983a8a33236b5d1bb6f4f37"
RETAG_HEAD = "5" * 40


def retag(
    *, tag_tree: str = SHARED_TREE, app: str = "VALUE = 1", base: str = BASE
) -> tuple[Repository, dict[str, dict[str, object]]]:
    """
    backend-common#217's retag: the bump branch moved from `PR217` to `v217`, two commits of
    one backend-common tree, so the consumer tree changed only in the pin's text.
    """
    repository = Repository()
    repository.shared = {PR_COMMIT: SHARED_TREE, TAG_COMMIT: tag_tree}
    before = repository.consumer("PR217", PR_COMMIT)
    after = repository.consumer("v217", TAG_COMMIT, app)
    merges = {
        MERGE: merge(before, (BASE, repository.head(HEAD, before))),
        RECREATED_MERGE: merge(after, (base, repository.head(RETAG_HEAD, after))),
    }
    return repository, merges


def test_a_retag_to_an_identical_tree_keeps_every_receipt() -> None:
    """
    INVARIANT: the receipt names what was tested, with first-party pins as the tree they install.

    After backend-common#217 merged, retagging the bump PRs from PR217 to v217 (one tree)
    re-ran every lane: backend's image build, migrations and OpenSearch, ai's type check and
    Trivy, for inputs byte-identical to the ones just validated.
    """
    repository, merges = retag()
    assert (
        action_receipt(merges, MERGE, repository, token="dependency-token")[0]
        == action_receipt(merges, RECREATED_MERGE, repository, token="dependency-token")[0]
    )


@pytest.mark.parametrize(
    "change",
    [{"tag_tree": "9" * 40}, {"app": "VALUE = 2"}, {"base": OTHER_HEAD}],
    ids=["other-pinned-tree", "other-file", "other-base"],
)
def test_a_retag_that_changes_what_runs_changes_the_receipt(change: dict[str, str]) -> None:
    """CONTROL: normalization ignores only the pin's spelling, never what it installs or anything else."""
    repository, merges = retag(**change)
    assert (
        action_receipt(merges, MERGE, repository, token="dependency-token")[0]
        != action_receipt(merges, RECREATED_MERGE, repository, token="dependency-token")[0]
    )


def test_without_the_dependency_token_pins_stay_exact() -> None:
    """Resolving a pin needs read access to backend-common; without it the receipt stays exact, and says so."""
    repository, merges = retag()
    before, warnings = action_receipt(merges, MERGE, repository)
    assert before != action_receipt(merges, RECREATED_MERGE, repository)[0]
    assert any("pins are compared exactly" in warning for warning in warnings)


@pytest.mark.parametrize("change,unchanged", [("source", True), ("retag", True), ("dependency", False)])
def test_inventory_receipt_tracks_inventory_inputs_not_application_pushes(change: str, unchanged: bool) -> None:
    repository, merges = retag(
        app="VALUE = 2" if change == "source" else "VALUE = 1",
        tag_tree="9" * 40 if change == "dependency" else SHARED_TREE,
    )
    paths = ("pyproject.toml", "uv.lock", ".github/workflows", "Dockerfile")
    before = action_receipt(merges, MERGE, repository, token="dependency-token", inventory_paths=paths)[0]
    after = action_receipt(merges, RECREATED_MERGE, repository, token="dependency-token", inventory_paths=paths)[0]
    assert (before == after) is unchanged


@pytest.mark.parametrize("change", ["recipe", "add", "delete"])
def test_inventory_recipe_changes_invalidate_evidence(change: str) -> None:
    repository = Repository()
    before = repository.tree({"uv.lock": "locked", "Dockerfile": "FROM python@sha256:a"})
    files = {"uv.lock": "locked", "Dockerfile": "FROM python@sha256:a"}
    if change == "recipe":
        files["Dockerfile"] = "FROM python@sha256:b"
    elif change == "add":
        files[".trivyignore"] = "CVE-example"
    else:
        del files["Dockerfile"]
    after = repository.tree(files)
    merges = {MERGE: merge(before), RECREATED_MERGE: merge(after)}
    paths = ("uv.lock", "Dockerfile", ".trivyignore")
    assert (
        action_receipt(merges, MERGE, repository, inventory_paths=paths)[0]
        != action_receipt(merges, RECREATED_MERGE, repository, inventory_paths=paths)[0]
    )
