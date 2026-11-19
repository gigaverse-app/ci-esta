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
let runLists = 0, inFlight = 0, peak = 0, jobLists = 0;
const runs = input.runs.map((run) => ({workflow_id: 55, status: 'completed', run_attempt: 1, ...run,
  updated_at: new Date(now - run.minutes_ago * 60000).toISOString(),
  created_at: new Date(now - (run.created_minutes_ago ?? run.minutes_ago) * 60000).toISOString()}));
const github = strictGithub({actions: {
  getWorkflowRun: async ({run_id}) => ({data: {id: run_id, workflow_id: 55}}),
  listWorkflowRuns: async (args) => {
    runLists += 1;
    if (args.event !== 'push' || args.branch !== 'main' || args.workflow_id !== 55) throw new Error(`unexpected ${JSON.stringify(args)}`);
    // Only the proof window: the branch's whole history grows without bound.
    if (!/^(>=|<)\d{4}-\d{2}-\d{2}T/.test(args.created || '')) throw new Error(`unbounded run listing ${JSON.stringify(args)}`);
    const since = Date.parse(args.created.replace(/^(>=|<)/, ''));
    return {data: {workflow_runs: runs.filter(run => args.created.startsWith('>=')
      ? Date.parse(run.created_at) >= since : Date.parse(run.created_at) < since)}};
  },
  listJobsForWorkflowRun: async ({run_id}) => {
    jobLists += 1; inFlight += 1; peak = Math.max(peak, inFlight);
    await new Promise((resolve) => setTimeout(resolve, input.delay_ms ?? 0));
    inFlight -= 1;
    return {data: {jobs: input.jobs[run_id] || []}};
  },
}});
const logs = [];
const core = {info: (m) => logs.push(m), warning: (m) => logs.push(m)};
const context = {runId: 999, repo: {owner: 'o', repo: 'r'}, payload: {repository: {default_branch: input.branch ?? 'main'}}};
(async () => {
 const cache = new Map(); let proof;
 for (let index = 0; index < (input.repeat ?? 1); index++) {
  proof = await trustedPushProof({github, context, core, jobName: input.job, receipt: input.receipt,
    cache, nowMs: now + index * 60000});
 }
 console.log(JSON.stringify({proof: proof ? {run: proof.run.id, jobs: proof.jobs.map((j) => j.id)} : null, logs, runLists, peak, jobLists}));
})();
"""


def job(job_id: int, conclusion: str = "success", receipt: str = RECEIPT, step: str = "success") -> dict:
    step_conclusion = step if conclusion == "success" else "skipped"
    return {"id": job_id, "name": JOB, "conclusion": conclusion, "steps": [{"name": receipt, "conclusion": step_conclusion}]}


def resolve(
    runs: list[dict], jobs: dict, *, receipt: str = RECEIPT, branch: str = "main", repeat: int = 1, delay_ms: int = 0
) -> dict:
    case = {"runs": runs, "jobs": jobs, "receipt": receipt, "job": JOB, "branch": branch, "repeat": repeat,
            "delay_ms": delay_ms}
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


def test_a_failed_rerun_revokes_older_default_branch_proof() -> None:
    runs = [
        {"id": 1, "head_sha": "c" * 40, "minutes_ago": 30},
        {"id": 2, "head_sha": "d" * 40, "minutes_ago": 5, "run_attempt": 2},
    ]
    assert resolve(runs, {"1": [job(11)], "2": [job(21, conclusion="failure")]})["proof"] is None


def test_an_old_run_rerun_recently_cannot_hide_outside_the_creation_window() -> None:
    runs = [
        {"id": 1, "head_sha": "c" * 40, "minutes_ago": 30},
        {"id": 2, "head_sha": "d" * 40, "minutes_ago": 5, "created_minutes_ago": 3 * 24 * 60, "run_attempt": 2},
    ]
    assert resolve(runs, {"1": [job(11)], "2": [job(21, conclusion="failure")]})["proof"] is None


def test_lanes_share_one_observation_time_and_one_history_snapshot() -> None:
    outcome = resolve([{ "id": 1, "head_sha": "c" * 40, "minutes_ago": 10}], {"1": [job(11)]}, repeat=2)
    assert outcome["proof"] is not None
    assert outcome["runLists"] == 2  # One recent index and one revocation index, shared by both calls.


def _unrelated_runs(count: int) -> tuple[list[dict], dict]:
    runs = [{"id": index, "head_sha": f"{index:040x}", "minutes_ago": index} for index in range(1, count + 1)]
    return runs, {str(index): [job(index * 10, receipt="Validated inputs other")] for index in range(1, count + 1)}


def test_a_day_of_unrelated_push_runs_is_read_concurrently_not_one_by_one() -> None:
    runs, jobs = _unrelated_runs(36)
    outcome = resolve(runs, jobs, delay_ms=40)
    assert outcome["proof"] is None
    assert outcome["jobLists"] == 36
    assert 1 < outcome["peak"] <= 8


def test_reading_ahead_never_changes_which_run_decides() -> None:
    runs, jobs = _unrelated_runs(30)
    jobs["3"] = [job(31, conclusion="failure")]
    jobs["20"] = [job(201)]
    outcome = resolve(runs, jobs, delay_ms=5)
    assert outcome["proof"] is None
    assert any("failure" in line for line in outcome["logs"])
    # The window reads at most a few runs past the decisive one, never the whole day.
    assert outcome["jobLists"] <= 3 + 8
