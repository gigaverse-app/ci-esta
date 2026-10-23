"""Dynamic coverage is part of a receipt, while failures retain a stable job identity."""

import json
import os
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
ACTION = ROOT / "actions/resolve-lane-evidence"


def admission(context: str, prior_context: str, *, later_failure: bool = False, attempt: int = 1) -> dict:
    script = yaml.safe_load((ACTION / "action.yml").read_text())["runs"]["steps"][0]["with"]["script"]
    harness = r"""
const input = JSON.parse(process.env.CONTEXT_CASE);
const {validationReceipt} = require(process.env.GITHUB_ACTION_PATH + '/inputs.cjs');
const {strictGithub} = require(process.env.GITHUB_REST_FAKE);
const head = 'f'.repeat(40), base = '0'.repeat(40), merge = 'a'.repeat(40);
const previous = validationReceipt(process.env.GITHUB_ACTION_PATH, `commit ${merge}`, input.prior);
const other = validationReceipt(process.env.GITHUB_ACTION_PATH, `commit ${merge}`, 'different failed scope');
const now = Date.now();
const run = (id, conclusion, sha) => ({id, workflow_id:55, head_sha:sha, status:'completed',
  conclusion, run_attempt:1, event:'pull_request', pull_requests:[{number:42}],
  updated_at:new Date(now - (3-id)*60000).toISOString()});
const runs = [run(1, 'success', head)];
if (input.failure) runs.unshift(run(2, 'failure', 'e'.repeat(40)));
const jobs = {
  1:[{name:'Validation', conclusion:'success', steps:[{name:previous, conclusion:'success'}]}],
  2:[{name:'Validation', conclusion:'failure', steps:[{name:other, conclusion:'skipped'}]}],
};
const github = strictGithub({
  git:{getCommit:async()=>{throw Error('use exact merge fallback');}},
  actions:{
    getWorkflowRun:async({run_id})=>({data:run_id===9999 ? {id:9999,workflow_id:55} : runs.find(r=>r.id===run_id)}),
    listWorkflowRuns:async()=>({data:{workflow_runs:runs}}),
    listJobsForWorkflowRun:async({run_id})=>({data:{jobs:jobs[run_id]}}),
  },
  checks:{listForRef:async()=>({data:{check_runs:[]}})},
  repos:{getCommit:async()=>({data:{parents:[]}}),compareCommitsWithBasehead:async()=>({data:{status:'diverged'}})},
});
const outputs = {}, warnings = [];
const core = {setOutput:(key,value)=>outputs[key]=value,warning:message=>warnings.push(message),info:()=>{}};
const context = {eventName:'pull_request',runId:9999,repo:{owner:'o',repo:'r'},payload:{pull_request:{
  number:42,base:{sha:base},head:{sha:head,ref:'branch',repo:{full_name:'o/r'}}}}};
const AsyncFunction = Object.getPrototypeOf(async function(){}).constructor;
new AsyncFunction('github','context','core','require','process','getOctokit',input.script)(
  github,context,core,require,process,()=>{throw Error('unexpected dependency client');}
).then(()=>console.log(JSON.stringify({outputs,warnings}))).catch(error=>{console.error(error);process.exit(1);});
"""
    result = subprocess.run(
        ["node", "-e", harness],
        env={
            **os.environ,
            "CONTEXT_CASE": json.dumps({"script": script, "prior": prior_context, "failure": later_failure}),
            "GITHUB_ACTION_PATH": str(ACTION),
            "GITHUB_REST_FAKE": str(ROOT / "tests/ci/github_rest_fake.cjs"),
            "GITHUB_RUN_ATTEMPT": str(attempt),
            "TESTED_MERGE_SHA": "a" * 40,
            "EVIDENCE_EXECUTION_CONTEXT": context,
            "EVIDENCE_LANES": '{"tests":"Validation"}',
            "EVIDENCE_INPUT_PATHS": "[]",
            "DEPENDENCY_TOKEN": "",
        },
        capture_output=True,
        text=True,
        check=True,
    )
    parsed = json.loads(result.stdout)
    # The only intended API failure is the identity lookup, which safely binds the exact merge.
    assert len(parsed["warnings"]) == 1, parsed["warnings"]
    return parsed["outputs"]


@pytest.mark.parametrize("context", ["", "library", "integration", '{"library":true,"integration":true}'])
def test_identical_execution_context_reuses_its_success(context: str) -> None:
    assert json.loads(admission(context, context)["reused"]) == {"tests": True}


@pytest.mark.parametrize("prior", ["", "library", "integration"])
def test_narrower_or_unscoped_proof_cannot_validate_combined_work(prior: str) -> None:
    assert json.loads(admission("library+integration", prior)["reused"]) == {}


def test_failure_in_another_context_and_head_revokes_older_success() -> None:
    assert json.loads(admission("library+integration", "library+integration", later_failure=True)["reused"]) == {}


def test_explicit_rerun_executes_even_with_matching_context() -> None:
    assert json.loads(admission("library", "library", attempt=2)["reused"]) == {}
