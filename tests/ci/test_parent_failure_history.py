"""Exercise the published github-script against the worker and its parent's distinct histories."""
import os
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
ACTION = ROOT / "actions/resolve-previous-failures/action.yml"


@pytest.mark.parametrize(("parent", "latest", "expected"), [
    ("41", "failure", "39"), ("41", "success", ""), ("", "failure", "79"),
    ("41", "mismatched-commit", None), ("41", "foreign-parent", None),
])
def test_failure_history_uses_the_workflow_that_owns_the_work(parent: str, latest: str, expected: str | None):
    step = yaml.safe_load(ACTION.read_text())["runs"]["steps"][0]
    harness = r"""
const assert = require('node:assert/strict');
const {strictGithub} = require('./tests/ci/github_rest_fake.cjs');
const context = {repo: {owner:'owner', repo:'repo'}, runId:81, sha:'abc', ref:'refs/heads/worker', payload:{}};
const parent = Boolean(process.env.PARENT_RUN_ID);
const id = parent ? 41 : 81;
const branch = parent ? 'feature' : 'worker';
const github = strictGithub({actions:{
  getWorkflowRun: async p => {
    assert.equal(p.run_id, id);
    return {data:{id, workflow_id:id+1, run_number:10, head_sha:process.env.LATEST==='mismatched-commit'?'def':'abc', head_branch:branch,
      created_at:'2026-01-01T10:00:00Z', head_repository:{id:1, full_name:process.env.LATEST==='foreign-parent'?'fork/repo':'owner/repo'}}};
  },
  listWorkflowRuns: async p => {
    assert.equal(p.branch, branch);
    assert.equal(p.workflow_id, id+1);
    const run = (offset, number, conclusion) => ({id:id+offset, run_number:number, conclusion, head_repository:{id:1}});
    return {data:{workflow_runs:[
      run(1,11,'failure'), run(0,10,'failure'), {...run(-1,9,'failure'),head_repository:{id:2}}, run(-1,9,'cancelled'),
      run(-2,8,process.env.LATEST), run(-3,7,'failure')
    ]}};
  }
}});
const core = {info(){}, setOutput(key,value){assert.equal(key,'run-id');process.stdout.write(value)}};
"""
    node = harness + "\n(async()=>{\n" + step["with"]["script"] + "\n})().catch(e=>{console.error(e);process.exit(1)})"
    result = subprocess.run(["node", "-e", node], cwd=ROOT, text=True, capture_output=True,
                            env={**os.environ, "PARENT_RUN_ID": parent, "LATEST": latest})
    if expected is None:
        assert result.returncode != 0
        assert "match the tested revision" in result.stderr
    else:
        assert result.returncode == 0, result.stderr
        assert result.stdout == expected
