"""Scheduled selection must never advance past unvalidated work."""

import json
import os
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize(
    "case,expected",
    [("success", "a" * 40), ("skipped-night", "a" * 40)]
    + [
        (case, "")
        for case in (
            "failure",
            "cancelled",
            "in-progress",
            "no-marker",
            "wrong-branch",
            "wrong-workflow",
            "manual",
            "stale",
            "diverged",
            "missing",
            "api-error",
            "jobs-error",
            "compare-error",
            "failed-marker",
            "failed-gate",
        )
    ],
)
def test_scheduled_base_requires_successful_execution(case, expected):
    action = yaml.safe_load((ROOT / "actions/resolve-scheduled-base/action.yml").read_text())
    script = r"""
const {strictGithub} = require(process.env.STRICT_FAKE);
const row = {id: 10, workflow_id: 7, event: 'schedule', head_branch: 'main',
  head_sha: 'a'.repeat(40), status: 'completed', conclusion: 'success',
  created_at: new Date(Date.now() - 24 * 3600000).toISOString()};
const kind = process.env.CASE;
if (['failure', 'cancelled'].includes(kind)) row.conclusion = kind;
if (kind === 'in-progress') row.status = 'in_progress';
if (kind === 'wrong-branch') row.head_branch = 'other';
if (kind === 'wrong-workflow') row.workflow_id = 8;
if (kind === 'manual') row.event = 'workflow_dispatch';
if (kind === 'stale') row.created_at = '2020-01-01T00:00:00Z';
const calls = [];
const github = strictGithub({actions: {
  getWorkflowRun: async () => ({data: {workflow_id: 7}}),
  listWorkflowRuns: async (args) => {
    calls.push(args);
    if (kind === 'api-error') throw Error('offline');
    return {data: {workflow_runs: kind === 'missing' ? [] :
      kind === 'skipped-night' ? [{...row, id: 11}, row] : [row, {...row, id: 9, status: 'completed', conclusion: 'success'}]}};
  },
  listJobsForWorkflowRun: async ({run_id}) => {
    if (kind === 'jobs-error') throw Error('offline');
    return {data: {jobs: [{name: 'Validation', conclusion: kind === 'failed-gate' ? 'failure' : 'success',
      steps: kind === 'no-marker' || run_id === 11 ? [] : [{name: 'Deep validation v1', conclusion: kind === 'failed-marker' ? 'failure' : 'success'}]}]}};
  },
}, repos: {
  compareCommitsWithBasehead: async () => {
    if (kind === 'compare-error') throw Error('offline');
    return {data: {status: kind === 'diverged' ? 'diverged' : 'ahead'}};
  },
}});
const outputs = {};
const core = {setOutput: (k,v) => outputs[k] = v, warning: () => {}, info: () => {}};
const context = {repo: {owner: 'org', repo: 'repo'}, runId: 99};
const AsyncFunction = Object.getPrototypeOf(async function(){}).constructor;
new AsyncFunction('github', 'context', 'core', process.env.ACTION_SCRIPT)(github, context, core)
  .then(() => console.log(JSON.stringify({outputs, calls})));
"""
    result = subprocess.run(
        ["node", "-e", script],
        capture_output=True,
        text=True,
        check=True,
        env=os.environ
        | {
            "STRICT_FAKE": str(ROOT / "tests/ci/github_rest_fake.cjs"),
            "GITHUB_ACTION_PATH": str(ROOT / "actions/resolve-scheduled-base"),
            "ACTION_SCRIPT": action["runs"]["steps"][0]["with"]["script"],
            "CASE": case,
            "HEAD_SHA": "b" * 40,
            "BRANCH": "main",
            "EVIDENCE_JOB": "Validation",
            "EVIDENCE_STEP": "Deep validation v1",
            "MAX_AGE_HOURS": "168",
        },
    )
    evidence = json.loads(result.stdout)
    assert evidence["outputs"]["base-sha"] == expected
    assert evidence["calls"][0]["event"] == "schedule"
    assert evidence["calls"][0]["branch"] == "main"


def test_explicit_scheduled_deep_keeps_affected_scope():
    from ci_esta.policy import Policy, Request, Work, plan

    result = plan(
        Policy(),
        Request(profile="affected_deep", occasion="schedule", revision="abc", affected={"slow"}),
        (Work(id="slow", tags={"expensive"}), Work(id="unaffected", tags={"expensive"})),
    )
    assert [item.work.id for item in result.runnable] == ["slow"]
    assert result.runnable[0].fresh
