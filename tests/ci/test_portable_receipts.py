"""Execution evidence is independent of private repositories and local cache files."""

import json
import subprocess
from pathlib import Path

import pytest

MODULE = Path(__file__).resolve().parents[2] / ".github/actions/resolve-lane-evidence/inputs.cjs"


def node(script: str, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["node", "-e", script, MODULE.as_posix(), *args], capture_output=True, text=True)


def test_receipt_covers_packaged_tools_and_ignores_generated_caches(tmp_path: Path) -> None:
    action = tmp_path / ".github/actions/resolve-lane-evidence"
    action.mkdir(parents=True)
    source = tmp_path / "src/ci_esta/tool.py"
    source.parent.mkdir(parents=True)
    source.write_text("original")
    script = "console.log(require(process.argv[1]).validationReceipt(process.argv[2], 'tree-identity'))"

    def receipt() -> str:
        result = node(script, str(action))
        assert result.returncode == 0, result.stderr
        return result.stdout

    first = receipt()
    cache = source.parent / "__pycache__/tool.pyc"
    cache.parent.mkdir()
    cache.write_bytes(b"generated")
    assert receipt() == first
    source.write_text("changed")
    assert receipt() != first


@pytest.mark.parametrize("paths", [[], ["."], ["a/../b"], ["/etc"], ["a\\b"], ["a//b"], ["a/./b"], ["a*"], [""]])
def test_invalid_input_paths_cannot_produce_reusable_evidence(paths: list[str]) -> None:
    script = """
const {inventoryIdentity}=require(process.argv[1]);
const {strictGithub}=require(process.argv[1].replace(".github/actions/resolve-lane-evidence/inputs.cjs", "tests/ci/github_rest_fake.cjs"));
const github=strictGithub({git:{getCommit:async()=>({data:{tree:{sha:'root'}}}),getTree:async()=>({data:{tree:[]}})}});
inventoryIdentity(github,null,{},'commit',JSON.parse(process.argv[2])).then(()=>process.exit(1),()=>process.exit(0));
"""
    result = node(script, json.dumps(paths))
    assert result.returncode == 0, result.stderr


def test_declared_input_changes_invalidate_evidence_but_unrelated_changes_do_not() -> None:
    script = """
const {inventoryIdentity}=require(process.argv[1]);
let selected='lock-v1',other='app-v1';
const {strictGithub}=require(process.argv[1].replace(".github/actions/resolve-lane-evidence/inputs.cjs", "tests/ci/github_rest_fake.cjs"));
const github=strictGithub({git:{getCommit:async()=>({data:{tree:{sha:'root'}}}),getTree:async()=>({data:{tree:[
{path:'lock',type:'blob',mode:'100644',sha:selected},{path:'app',type:'blob',mode:'100644',sha:other}]}})}});
(async()=>{
const read=()=>inventoryIdentity(github,null,{},'commit',['lock']);
const before=await read();other='app-v2';const unrelated=await read();selected='lock-v2';const changed=await read();
console.log(JSON.stringify({before,unrelated,changed}));
})();
"""
    result = node(script)
    assert result.returncode == 0, result.stderr
    values = json.loads(result.stdout)
    assert values["before"] == values["unrelated"]
    assert values["before"] != values["changed"]
