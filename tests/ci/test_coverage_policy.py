"""Execute the shared admission policy with event/API fixtures."""

import os
import subprocess
from pathlib import Path


def test_coverage_admission() -> None:
    script = Path(__file__).resolve().parents[2] / "scripts/ci/coverage-policy.cjs"
    result = subprocess.run(
        [
            "node",
            "-e",
            r"""
const assert = require('node:assert/strict');
const decide = require(process.argv[1]);
const { strictGithub } = require(process.env.GITHUB_REST_FAKE);
async function run(eventName, {labels=[], explicit=false, artifacts=[], ref='refs/heads/main', error=false}={}) {
  let calls=0;
  const outputs={};
  await decide({
    context: {eventName, ref, sha:'abc123', repo:{owner:'org',repo:'repo'},
      payload:{pull_request:{labels:labels.map(name=>({name}))}}},
    github:strictGithub({actions:{listArtifactsForRepo:async()=>{
      calls++; if(error) throw Error('API unavailable');
      return {data:{artifacts}};
    }}}),
    core:{setOutput:(key,value)=>outputs[key]=value, info:()=>{}, warning:()=>{}},
    explicit,
  });
  return {...outputs,calls};
}
(async()=>{
  for (const event of ['pull_request','push','workflow_dispatch','workflow_call']) {
    const result=await run(event);
    assert.equal(result.enabled,false,event);
    assert.equal(result.calls,0,event+' must not consult coverage history');
  }
  assert.equal((await run('pull_request',{labels:['test:full']})).enabled,false);
  assert.equal((await run('pull_request',{labels:['run-coverage']})).enabled,true);
  assert.equal((await run('workflow_dispatch',{explicit:true})).enabled,true);
  assert.equal((await run('schedule')).enabled,true);
  assert.equal((await run('schedule',{ref:'refs/heads/staging'})).enabled,false);
  assert.equal((await run('schedule',{artifacts:[{expired:false}]})).enabled,false);
  assert.equal((await run('schedule',{artifacts:[{expired:true}]})).enabled,true);
  assert.equal((await run('schedule',{error:true})).enabled,true);
  assert.equal((await run('schedule')).marker,'coverage-main-abc123');
})().catch(error=>{console.error(error);process.exitCode=1;});
""",
            str(script),
        ],
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "GITHUB_REST_FAKE": str(script.parents[2] / "tests/ci/github_rest_fake.cjs")},
    )
    assert result.returncode == 0, result.stdout + result.stderr
