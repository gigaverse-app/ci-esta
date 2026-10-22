"""A delayed cleanup step must never cancel newer validation."""

import json
import os
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize(
    "scenario,expected",
    [("current", [90]), ("stale", []), ("advanced", []), ("unavailable", []), ("missing_order", []), ("missing_caller_order", []), ("force", [90])],
)
def test_cleanup_requires_live_head_and_older_same_workflow_run(scenario: str, expected: list[int]) -> None:
    action = yaml.safe_load((ROOT / ".github/actions/cancel-obsolete-pr-runs/action.yml").read_text())
    script = action["runs"]["steps"][0]["with"]["script"]
    harness = r"""
const {strictGithub}=require(process.env.STRICT_FAKE);
const scenario=process.env.SCENARIO;
let liveHead=scenario==='stale'?'new':'current';
const cancelled=[], forced=[], warnings=[];
const base={workflow_id:7, status:'in_progress', head_sha:'old', run_number:9,
  head_repository:{full_name:'org/repo'},head_branch:'feature',pull_requests:[{number:123}]};
const runs=[
  {...base,id:90,run_number:scenario==='missing_order'?undefined:9},
  {...base,id:100,head_sha:'current',run_number:scenario==='missing_caller_order'?undefined:10},
  {...base,id:110,head_sha:'new',run_number:11},
  {...base,id:80,workflow_id:8},
  {...base,id:70,head_branch:'other',pull_requests:[{number:456}]},
  {...base,id:60,status:'completed'},
  {...base,id:50,head_sha:'current'},
];
const github=strictGithub({
  repos:{
    getBranch:async()=>{if(scenario==='unavailable')throw Error('API unavailable');return {data:{commit:{sha:liveHead}}};},
    getCommit:async()=>({data:{parents:[{sha:'old'}]}}),
  },
  checks:{listForRef:async()=>({data:{check_runs:[{details_url:'https://github.com/org/repo/actions/runs/90'}]}})},
  actions:{
    getWorkflowRun:async({run_id})=>({data:{...runs.find(r=>r.id===run_id),status:cancelled.includes(run_id)&&scenario!=='force'?'completed':'in_progress'}}),
    listWorkflowRuns:async()=>{if(scenario==='advanced')liveHead='new';return {data:{workflow_runs:runs}};},
    cancelWorkflowRun:async({run_id})=>{cancelled.push(run_id);},
    forceCancelWorkflowRun:async({run_id})=>{forced.push(run_id);},
  },
});
const AsyncFunction=Object.getPrototypeOf(async function(){}).constructor;
new AsyncFunction('github','context','core','setTimeout',process.env.ACTION_SCRIPT)(
  github,{repo:{owner:'org',repo:'repo'},runId:100,payload:{before:'old'}},
  {info:()=>{},notice:()=>{},warning:m=>warnings.push(m)},fn=>fn()
).then(()=>console.log(JSON.stringify({cancelled,forced,warnings}))).catch(e=>{console.error(e);process.exit(1);});
"""
    result = subprocess.run(
        ["node", "-e", harness], check=True, capture_output=True, text=True,
        env=os.environ | {
            "STRICT_FAKE": str(ROOT / "tests/ci/github_rest_fake.cjs"), "ACTION_SCRIPT": script,
            "PR_NUMBER": "123", "CURRENT_HEAD_SHA": "current", "HEAD_REF": "feature", "SCENARIO": scenario,
        },
    )
    observed = json.loads(result.stdout)
    assert observed["cancelled"] == expected
    assert observed["forced"] == ([90] if scenario == "force" else [])
    assert bool(observed["warnings"]) is (scenario == "unavailable")
