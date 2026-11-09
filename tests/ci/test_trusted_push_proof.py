"""The default branch's own push runs prove lanes for identical receipts; anything weaker executes."""

import json
import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
MODULE = ROOT / "actions/resolve-lane-evidence/trusted.cjs"
FAKE = ROOT / "tests/ci/github_rest_fake.cjs"
RECEIPT = "Validated inputs " + "a" * 64
JOB = "Test (Python 3.11, ubuntu-latest)"

HARNESS = r"""
const input = JSON.parse(process.env.CASE);
const {strictGithub} = require(process.env.GITHUB_REST_FAKE);
const {trustedPushProof} = require(process.env.MODULE);
const now = Date.now();
const runs = input.runs.map((run) => ({workflow_id: 55, status: 'completed', run_attempt: 1, ...run,
  updated_at: new Date(now - run.minutes_ago * 60000).toISOString()}));
const github = strictGithub({actions: {
  getWorkflowRun: async ({run_id}) => ({data: {id: run_id, workflow_id: 55}}),
  listWorkflowRuns: async (args) => {
    if (args.event !== 'push' || args.branch !== 'main' || args.workflow_id !== 55) throw new Error(`unexpected ${JSON.stringify(args)}`);
    return {data: {workflow_runs: runs}};
  },
  listJobsForWorkflowRun: async ({run_id}) => ({data: {jobs: input.jobs[run_id] || []}}),
}});
const logs = [];
const core = {info: (m) => logs.push(m), warning: (m) => logs.push(m)};
const context = {runId: 999, repo: {owner: 'o', repo: 'r'}, payload: {repository: {default_branch: input.branch ?? 'main'}}};
trustedPushProof({github, context, core, jobName: input.job, receipt: input.receipt}).then((proof) => {
  console.log(JSON.stringify({proof: proof ? {run: proof.run.id, jobs: proof.jobs.map((j) => j.id)} : null, logs}));
});
"""


def job(job_id: int, conclusion: str = "success", receipt: str = RECEIPT, step: str = "success") -> dict:
    step_conclusion = step if conclusion == "success" else "skipped"
    return {"id": job_id, "name": JOB, "conclusion": conclusion, "steps": [{"name": receipt, "conclusion": step_conclusion}]}


def resolve(runs: list[dict], jobs: dict, *, receipt: str = RECEIPT, branch: str = "main") -> dict:
    case = {"runs": runs, "jobs": jobs, "receipt": receipt, "job": JOB, "branch": branch}
    result = subprocess.run(
        ["node", "-e", HARNESS], capture_output=True, text=True,
        env={**os.environ, "CASE": json.dumps(case), "MODULE": str(MODULE), "GITHUB_REST_FAKE": str(FAKE)},
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_an_identical_receipt_on_a_default_branch_push_proves_the_lane() -> None:
    # pytest-selective 1.1.1: the release's base (#109, docs only) never ran the tests, but an
    # earlier push to main proved identical inputs minutes before.
    result = resolve([{"id": 1, "head_sha": "c" * 40, "minutes_ago": 10}], {"1": [job(11)]})
    assert result["proof"] == {"run": 1, "jobs": [11]}


def test_the_newest_run_decides_and_a_newer_failure_revokes_older_proof() -> None:
    runs = [{"id": 1, "head_sha": "c" * 40, "minutes_ago": 30}, {"id": 2, "head_sha": "d" * 40, "minutes_ago": 5}]
    result = resolve(runs, {"1": [job(11)], "2": [job(21, conclusion="failure")]})
    assert result["proof"] is None
    assert any("failure" in line for line in result["logs"])


@pytest.mark.parametrize(
    "run, jobs",
    [
        ({"id": 1, "head_sha": "c" * 40, "minutes_ago": 10, "run_attempt": 2}, {"1": [job(11)]}),  # a rerun
        ({"id": 1, "head_sha": "c" * 40, "minutes_ago": 25 * 60}, {"1": [job(11)]}),  # older than a day
        ({"id": 1, "head_sha": "c" * 40, "minutes_ago": 10}, {"1": [job(11, receipt="Validated inputs other")]}),
        ({"id": 1, "head_sha": "c" * 40, "minutes_ago": 10}, {"1": []}),  # the lane did not run
        ({"id": 999, "head_sha": "c" * 40, "minutes_ago": 0}, {"999": [job(11)]}),  # this very run
    ],
    ids=["rerun", "stale", "other-receipt", "lane-skipped", "self"],
)
def test_weaker_evidence_executes_fresh(run: dict, jobs: dict) -> None:
    assert resolve([run], jobs)["proof"] is None


def test_without_a_known_default_branch_nothing_is_trusted() -> None:
    assert resolve([{"id": 1, "head_sha": "c" * 40, "minutes_ago": 10}], {"1": [job(11)]}, branch="")["proof"] is None
