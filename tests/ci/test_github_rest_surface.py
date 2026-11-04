"""
Contract: shared JavaScript calls only REST methods the selected actions/github-script provides.

``resolve.cjs`` called ``github.rest.actions.listWorkflowRunsForWorkflow``. The real client
has no such method, so ``github.paginate(undefined)`` fetched the API root and every
same-head reuse silently fell back. Its test fake defined the same misspelled name, so
every test passed. These tests pin the real surface and make fakes unable to invent one.
"""

import json
import re
import subprocess
from pathlib import Path

import pytest

from scripts.ci.github_script_surface import main, rest_surface

ROOT = Path(__file__).resolve().parents[2]
SURFACE_FILE = ROOT / "tests/ci/github_script_rest_surface.json"
STRICT_FAKE = ROOT / "tests/ci/github_rest_fake.cjs"
SURFACE = json.loads(SURFACE_FILE.read_text(encoding="utf-8"))
REFERENCE = re.compile(r"actions/github-script@([^\s]+)")
REST_CALL = re.compile(r"github\.rest\.(\w+)\.(\w+)")
SHARED_SOURCES = [
    ".github/**/*.yml", ".github/**/*.yaml", ".github/**/*.cjs", ".github/**/*.js",
    "actions/**/*.yml", "actions/**/*.yaml", "actions/**/*.cjs", "actions/**/*.js", "scripts/**/*.cjs",
]
# Every call site this repo is known to rely on; a scanner that finds none of them is broken.
KNOWN_CALLS = {("actions", "getWorkflowRun"), ("actions", "listJobsForWorkflowRun"), ("repos", "getCommit")}


def _shared_sources() -> list[Path]:
    return sorted({path for pattern in SHARED_SOURCES for path in ROOT.glob(pattern) if path.is_file()})


def _rest_calls() -> dict[tuple[str, str], list[str]]:
    calls: dict[tuple[str, str], list[str]] = {}
    for path in _shared_sources():
        for match in REST_CALL.finditer(path.read_text(encoding="utf-8")):
            calls.setdefault((match.group(1), match.group(2)), []).append(str(path.relative_to(ROOT)))
    return calls


def _node(script: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["node", "-e", script, str(STRICT_FAKE)], capture_output=True, text=True, check=False, cwd=ROOT
    )


def test_every_github_script_major_matches_the_recorded_surface() -> None:
    refs = {match.group(1) for path in _shared_sources() for match in REFERENCE.finditer(path.read_text(encoding="utf-8"))}

    assert refs, "no actions/github-script found; the scan is broken"
    assert refs == {SURFACE["github_script_ref"]}, (
        f"actions/github-script refs {sorted(refs)} differ from the recorded surface "
        f"{SURFACE['github_script_ref']}; regenerate it (see scripts/ci/github_script_surface.py)"
    )


def test_shared_scripts_call_only_methods_the_recorded_client_provides() -> None:
    calls = _rest_calls()
    missing = {
        f"github.rest.{namespace}.{method} ({', '.join(sorted(set(paths)))})"
        for (namespace, method), paths in calls.items()
        if method not in SURFACE["rest"].get(namespace, [])
    }

    assert KNOWN_CALLS <= set(calls), "the scanner missed known call sites"
    assert not missing, f"calls the selected actions/github-script does not provide: {sorted(missing)}"


@pytest.mark.parametrize(
    ("script", "error"),
    [
        (
            "const {strictGithub}=require(process.argv[1]);"
            "strictGithub({actions:{listWorkflowRunsForWorkflow: async()=>({data:{}})}});",
            "listWorkflowRunsForWorkflow does not exist",
        ),
        (
            "const {strictGithub}=require(process.argv[1]);"
            "strictGithub({actions:{}}).rest.actions.listWorkflowRunsForWorkflow;",
            "listWorkflowRunsForWorkflow does not exist",
        ),
        (
            "const {strictGithub}=require(process.argv[1]);strictGithub({actions:{}}).rest.actions.listWorkflowRuns;",
            "does not implement github.rest.actions.listWorkflowRuns",
        ),
        (
            "const {strictGithub}=require(process.argv[1]);"
            "strictGithub({}).paginate(undefined,{}).catch(e=>{console.error(e.message);process.exit(1)});",
            "would fetch the API root",
        ),
    ],
    ids=["defines-missing-method", "calls-missing-method", "calls-unimplemented-method", "paginates-undefined"],
)
def test_the_strict_fake_rejects_what_the_real_client_would_not_do(script: str, error: str) -> None:
    completed = _node(script)

    assert completed.returncode != 0
    assert error in completed.stderr


def test_the_strict_fake_serves_a_real_method() -> None:
    """CONTROL: a method the recorded client provides works through the fake and its paginate."""
    completed = _node(
        "const {strictGithub}=require(process.argv[1]);"
        "const g=strictGithub({actions:{listWorkflowRuns: async()=>({data:{workflow_runs:[{id:7}]}})}});"
        "g.paginate(g.rest.actions.listWorkflowRuns,{}).then(r=>console.log(JSON.stringify(r)));"
    )

    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout) == [{"id": 7}]


HAND_BUILT_CLIENT = re.compile(r"\brest\s*:\s*\{")


def test_no_test_hand_builds_a_github_client() -> None:
    """Test fakes go through strictGithub, so they cannot define a method the real client lacks."""
    offenders = [
        str(path.relative_to(ROOT))
        for path in sorted((ROOT / "tests").rglob("*"))
        if path.suffix in {".py", ".cjs", ".js"}
        and path != STRICT_FAKE
        and path.is_file()
        and HAND_BUILT_CLIENT.search(path.read_text(encoding="utf-8"))
    ]

    assert not offenders, f"build github-script fakes with tests/ci/github_rest_fake.cjs: {offenders}"


BUNDLE = """\
var x = 1;
const Endpoints = {
  actions: {
    getWorkflowRun: ["GET /repos/{owner}/{repo}/actions/runs/{run_id}"],
    listWorkflowRuns: [
      "GET /repos/{owner}/{repo}/actions/workflows/{workflow_id}/runs"
    ],
  },
  git: {
    getCommit: ["GET /repos/{owner}/{repo}/git/commits/{commit_sha}"],
  },
};
var endpoints_default = Endpoints;
"""


def test_the_surface_is_parsed_from_the_bundled_endpoint_table() -> None:
    assert rest_surface(BUNDLE) == {"actions": ["getWorkflowRun", "listWorkflowRuns"], "git": ["getCommit"]}


@pytest.mark.parametrize(
    "bundle",
    ["var nothing = 1;\n", "const Endpoints = {\n  actions: {\n", "const Endpoints = {\n  git: {\n  },\n};\n"],
    ids=["no-table", "unterminated", "no-actions"],
)
def test_an_unrecognised_bundle_layout_is_refused(bundle: str) -> None:
    with pytest.raises(ValueError, match="layout changed"):
        rest_surface(bundle)


@pytest.mark.parametrize("ref_option", ["--ref", "--sha"])
def test_recorder_keeps_the_selected_ref_and_real_endpoint_table(tmp_path: Path, ref_option: str) -> None:
    bundle = tmp_path / "bundle.js"
    bundle.write_text(BUNDLE, encoding="utf-8")
    output = tmp_path / "surface.json"

    main([ref_option, "v9", "--bundle", str(bundle), "--output", str(output)])

    assert json.loads(output.read_text(encoding="utf-8")) == {
        "github_script_ref": "v9",
        "rest": {"actions": ["getWorkflowRun", "listWorkflowRuns"], "git": ["getCommit"]},
    }
