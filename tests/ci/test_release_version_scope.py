import json
import subprocess
from pathlib import Path

import pytest

from tests.testing.git_repo import commit, write

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "actions/resolve-lane-evidence/release_version.py"


@pytest.mark.parametrize("change, expected", [
    ("version", True), ("dependency", False), ("lock-dependency", False),
    ("source", False), ("workflow", False), ("test", False), ("comment", False),
    ("inconsistent", False), ("decrease", False), ("missing", False), ("unchanged", False),
])
def test_only_the_project_version_and_release_metadata_can_reuse_base_proof(tmp_path, change, expected):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    project = '[project]\nname = "example"\nversion = "1.5.1"\ndependencies = ["thing==1.5.1"]\n'
    lock = 'version = 1\n[[package]]\nname = "example"\nversion = "1.5.1"\nsource = { editable = "." }\n[[package]]\nname = "thing"\nversion = "1.5.1"\n'
    write(tmp_path, "pyproject.toml", project)
    write(tmp_path, "uv.lock", lock)
    write(tmp_path, ".release-please-manifest.json", '{".": "1.5.1"}\n')
    write(tmp_path, "CHANGELOG.md", "# Changelog\n")
    base = commit(tmp_path)
    version = "1.4.0" if change == "decrease" else "1.6.0"
    if change != "unchanged":
        write(tmp_path, "pyproject.toml", project.replace('version = "1.5.1"', f'version = "{version}"'))
        write(tmp_path, "uv.lock", lock.replace('version = "1.5.1"', f'version = "{version}"', 1))
        write(tmp_path, ".release-please-manifest.json", json.dumps({".": version}) + "\n")
        write(tmp_path, "CHANGELOG.md", "# Changelog\n## 1.6.0\nFeature\n")
    if change == "dependency":
        write(tmp_path, "pyproject.toml", (tmp_path / "pyproject.toml").read_text().replace("thing==1.5.1", "thing==1.6.0"))
    if change == "lock-dependency":
        write(tmp_path, "uv.lock", (tmp_path / "uv.lock").read_text().replace('version = "1.5.1"', 'version = "1.6.0"'))
    if change == "comment":
        write(tmp_path, "pyproject.toml", (tmp_path / "pyproject.toml").read_text() + "# other change\n")
    if change == "inconsistent":
        write(tmp_path, ".release-please-manifest.json", '{".": "2.0.0"}\n')
    if change in {"source", "workflow", "test"}:
        write(tmp_path, {"source": "src/example.py", "workflow": ".github/workflows/ci.yml", "test": "tests/test_value.py"}[change], "changed\n")
    if change == "missing":
        (tmp_path / "uv.lock").unlink()
    head = commit(tmp_path) if change != "unchanged" else base
    result = subprocess.run(["python3", str(SCRIPT), base, head], cwd=tmp_path, check=True, capture_output=True, text=True)
    value = json.loads(result.stdout)
    assert value["version_only"] is expected
    if expected:
        assert value["manifests"] == {"pyproject.toml": project, "uv.lock": lock}


def test_release_normalization_keeps_every_non_version_tool_input(tmp_path):
    project = '[project]\nname = "example"\nversion = "1.5.1"\n'
    lock = 'version = 1\n[[package]]\nname = "example"\nversion = "1.5.1"\nsource = {editable = "."}\n'
    action = tmp_path / "actions/resolve-lane-evidence"
    action.mkdir(parents=True)
    write(tmp_path, "actions/resolve-lane-evidence/helper.cjs", "original")
    write(tmp_path, "pyproject.toml", project)
    write(tmp_path, "uv.lock", lock)
    script = "const m=require(process.argv[1]); console.log(m.validationReceipt(process.argv[2], 'base-inputs', '', JSON.parse(process.argv[3])))"

    def receipt(overrides):
        return subprocess.check_output(["node", "-e", script, str(SCRIPT.with_name("inputs.cjs")), str(action), json.dumps(overrides)], text=True)

    before = receipt({})
    write(tmp_path, "pyproject.toml", project.replace("1.5.1", "1.6.0"))
    write(tmp_path, "uv.lock", lock.replace("1.5.1", "1.6.0"))
    assert receipt({}) != before
    overrides = {"pyproject.toml": project, "uv.lock": lock}
    assert receipt(overrides) == before
    write(tmp_path, "actions/resolve-lane-evidence/helper.cjs", "changed")
    assert receipt(overrides) != before


@pytest.mark.parametrize("event", ["pull_request", "push"])
def test_release_pr_and_its_merge_resolve_the_validated_base(tmp_path, event):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    for version in ["1.5.1", "1.6.0"]:
        write(tmp_path, "pyproject.toml", f'[project]\nname = "example"\nversion = "{version}"\n')
        write(tmp_path, "uv.lock", f'version = 1\n[[package]]\nname = "example"\nversion = "{version}"\nsource = {{editable = "."}}\n')
        write(tmp_path, ".release-please-manifest.json", json.dumps({".": version}))
        sha = commit(tmp_path)
        if version == "1.5.1":
            base = sha
    script = r"""
const {proofTarget}=require(process.argv[1]);
const {strictGithub}=require(process.argv[2]);
const [event,base,head]=process.argv.slice(3);
const pr=(sha,number)=>({number,merged:true,merge_commit_sha:sha,
  base:{sha:base,ref:'main',repo:{full_name:'o/r'}},head:{sha,ref:'feature',repo:{full_name:'o/r'}}});
const github=strictGithub({
  repos:{listPullRequestsAssociatedWithCommit:async({commit_sha})=>({data:[pr(commit_sha,commit_sha===base?7:8)]})},
  pulls:{get:async({pull_number})=>({data:pr(pull_number===7?base:head,pull_number)})},
  actions:{getWorkflowRun:async()=>({data:{workflow_id:12}}),listWorkflowRuns:async()=>({data:{workflow_runs:[]}})},
});
proofTarget({github,context:{repo:{owner:'o',repo:'r'},runId:99,eventName:event,ref:'refs/heads/main',payload:{pull_request:event==='pull_request'?pr(head,8):undefined}},
  core:{warning:()=>{}},actionPath:require('path').dirname(process.argv[1]),paths:['src','pyproject.toml','uv.lock'],
  sha:head,attempt:1,afterMerge:true,releaseVersion:true}).then(value=>console.log(JSON.stringify(value)));
"""
    result = json.loads(subprocess.check_output(["node", "-e", script, str(SCRIPT.with_name("merged.cjs")),
        str(ROOT / "tests/ci/github_rest_fake.cjs"), event, base, sha], cwd=tmp_path, text=True))
    assert result["releaseOnly"] is True
    assert result["sha"] == base
    assert result["pr"]["number"] == 7
