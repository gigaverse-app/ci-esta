"""Inventory admission has its own input identity and successful-job proof."""

import json
import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def decide(
    *, changed: bool = True, reused: bool = False, error: bool = False, mode: str = "pull_request", attempt: int = 1
) -> dict:
    script = r"""
const path = require('path');
const root = process.env.ACTIONS_ROOT;
const input = JSON.parse(process.env.INVENTORY_CASE);
const calls = [];
// The resolver's strict API/revocation tests cover which jobs can prove success.
// This test checks which evidence inventory requests, and how admission uses it.
require.cache[require.resolve(root + '/resolve-incremental-pr-base/resolve.cjs')] = {exports: {
 resolveIncrementalPrBase: async args => {
   calls.push({job: args.evidenceJobName, receipt: args.evidenceStepName, same: args.sameHeadOnly, ttl: args.maxAgeHours, conservative: args.conservativeFailures});
   return {reused: input.reused};
 }
}};
const {resolveInventory} = require(root + '/resolve-security-trigger/inventory.cjs');
const {strictGithub} = require(process.env.GITHUB_REST_FAKE);
const github = strictGithub({git: {
 getCommit: async ({commit_sha}) => { if(input.error) throw Error('unavailable'); return {data:{tree:{sha:commit_sha}}}; },
 getTree: async ({tree_sha}) => ({data:{tree:[{path:'uv.lock',mode:'100644',type:'blob',sha:input.changed ? tree_sha : 'same'}]}})
}});
(async () => {
 const result = await resolveInventory({github, shared:null, context:{repo:{owner:'org',repo:'repo'},payload:{pull_request:{number:42,head:{sha:'head',ref:'branch'},base:{sha:'base'}}}},
   core:{warning:()=>{}}, actionPath:root+'/resolve-security-trigger', paths:['uv.lock'], jobName:'Inventory scan', mode:input.mode});
 console.log(JSON.stringify({result,calls}));
})();
"""
    result = subprocess.run(
        ["node", "-e", script],
        env={
            **os.environ,
            "GITHUB_REST_FAKE": str(ROOT / "tests/ci/github_rest_fake.cjs"),
            "ACTIONS_ROOT": str(ROOT / "actions"),
            "GITHUB_RUN_ATTEMPT": str(attempt),
            "INVENTORY_CASE": json.dumps(dict(changed=changed, reused=reused, error=error, mode=mode)),
        },
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(result.stdout)


@pytest.mark.parametrize("reused", [True, False])
def test_changed_inventory_requires_its_own_fresh_success(reused: bool) -> None:
    outcome = decide(reused=reused)
    assert outcome["result"]["changed"] is (not reused)
    assert outcome["calls"] == [
        {
            "job": "Inventory scan",
            "receipt": outcome["result"]["receipt"],
            "same": True,
            "ttl": 24,
            "conservative": True,
        }
    ]


def test_unchanged_inventory_needs_no_prior_source_success() -> None:
    outcome = decide(changed=False)
    assert outcome["result"]["changed"] is False
    assert outcome["calls"] == []


def test_unreadable_inventory_requires_scan_without_reusable_receipt() -> None:
    assert decide(error=True)["result"] == {"changed": True, "receipt": ""}


@pytest.mark.parametrize("mode", ["manual", "schedule", "label", "comment"])
def test_explicit_and_scheduled_requests_never_use_cached_inventory(mode: str) -> None:
    assert decide(mode=mode) == {"result": None, "calls": []}


def test_explicit_rerun_reproduces_inventory_scan() -> None:
    outcome = decide(attempt=2, reused=True)
    assert outcome["result"]["changed"] is True
    assert outcome["calls"] == []
