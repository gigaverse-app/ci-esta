const assert = require('node:assert/strict');
const {test} = require('node:test');
const {strictGithub} = require('../ci/github_rest_fake.cjs');
const {mergedPullRequest} = require('../../actions/resolve-lane-evidence/merged.cjs');
const sha = 'a'.repeat(40);
const pr = {number:7, merged:true, merge_commit_sha:sha, base:{ref:'main',repo:{full_name:'o/r'}},
  head:{sha:'b'.repeat(40),ref:'feature',repo:{full_name:'o/r'}}};
for (const scenario of ['valid','fork','wrong-base','different-merge','unmerged','ambiguous','api-error','newer-failure','newer-cancelled','newer-timed_out','missing','rerun']) {
  test(`post-merge discovery preserves ${scenario}`, async () => {
    const candidate = structuredClone(pr);
    if (scenario === 'fork') candidate.head.repo.full_name = 'other/r';
    if (scenario === 'wrong-base') candidate.base.ref = 'other';
    if (scenario === 'different-merge') candidate.merge_commit_sha = 'c'.repeat(40);
    if (scenario === 'unmerged') candidate.merged = false;
    const github = strictGithub({
      repos:{listPullRequestsAssociatedWithCommit:async()=>{
        if(scenario==='api-error') throw Error('offline');
        return {data:scenario==='missing'?[]:scenario==='ambiguous'?[candidate,{...candidate,number:8}]:[candidate]};
      }},
      pulls:{get:async({pull_number})=>({data:{...candidate,number:pull_number}})},
      actions:{getWorkflowRun:async()=>({data:{workflow_id:12}}),listWorkflowRuns:async()=>({data:{workflow_runs:
        scenario.startsWith('newer-')?[{id:44,head_sha:sha,conclusion:scenario.slice(6),status:'completed'}]:[]}})},
    });
    const result = await mergedPullRequest({github,context:{repo:{owner:'o',repo:'r'},runId:99},
      sha, branch:'main', attempt:scenario==='rerun'?2:1, core:{warning:()=>{}}});
    assert.equal(result?.number ?? null, scenario==='valid'?7:null);
  });
}
