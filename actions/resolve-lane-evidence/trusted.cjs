const {evidenceSearch, newestFirst} = require('../resolve-incremental-pr-base/search.cjs');
const {receiptEvidence} = require('../resolve-incremental-pr-base/resolve.cjs');
// Proof from the default branch's own push runs.
//
// A pull request's runs prove a lane only for that pull request. The default branch's
// push runs execute its own, already-merged workflow, so they are trusted proof for any
// run whose receipt is identical: the same declared inputs, the same execution context
// and the same receipt format. This is what lets a version-only release reuse a lane
// that the release's base never ran (its merged pull request changed only documentation),
// because an earlier push to the default branch proved those identical inputs.

// The newest run decides: a newer failure of the same job with the same receipt revokes
// older successes, as it does for pull-request evidence.
async function trustedPushProof({github, context, core, jobName, receipt, maxAgeHours = 24, nowMs = Date.now(), cache = new Map()}) {
  const branch = context.payload.repository?.default_branch;
  if (!branch || !receipt) return null;
  const search = evidenceSearch(github, context, cache, nowMs);
  if (!search.canSearch(jobName, receipt)) return null;
  const {data: current} = await search.run(context.runId);
  const oldest = search.nowMs - maxAgeHours * 3600 * 1000;
  // Ask only for the window that can prove anything; the branch's whole history grows without bound.
  const since = new Date(oldest - 3600 * 1000).toISOString();
  const runs = await search.runs({workflow_id: current.workflow_id, branch, event: 'push',
    status: 'completed', created: `>=${since}`});
  const candidates = runs
    .filter((run) => run.id !== context.runId && Date.parse(run.updated_at) >= oldest && search.allows(jobName, receipt, run))
    .sort(newestFirst);
  for (const [index, run] of candidates.entries()) {
    search.readAheadJobs(candidates, index);
    const jobs = await search.jobs(run.id, run.run_attempt);
    const evidence = receiptEvidence(run, jobs, {jobName, receipt});
    if (evidence.contradicted) {
      search.refuse(jobName, receipt, 'newer contradictory default-branch evidence', run);
      core.info(`Default-branch run ${run.id} has '${jobName}' failure for these inputs; executing fresh.`);
      return null;
    }
    if (evidence.proven) {
      // Creation time scopes the cheap positive-proof search, not revocation.
      // An old run can finish/rerun now. Only once we have useful proof do we
      // load that older metadata, then inspect jobs solely for newer results.
      const older = await search.runs({workflow_id: current.workflow_id, branch, event: 'push',
        status: 'completed', created: `<${since}`});
      const laters = older.filter(other => other.id !== context.runId && newestFirst(other, run) < 0).sort(newestFirst);
      for (const [laterIndex, later] of laters.entries()) {
        search.readAheadJobs(laters, laterIndex);
        const laterEvidence = receiptEvidence(later, await search.jobs(later.id, later.run_attempt), {jobName, receipt});
        if (laterEvidence.contradicted) {
          search.refuse(jobName, receipt, 'newer result from an older default-branch run', later);
          core.info(`Default-branch run ${later.id} has a newer failure for these inputs; executing fresh.`);
          return null;
        }
      }
      core.info(`Default-branch run ${run.id} (${run.head_sha.slice(0, 7)}) proved '${jobName}' for identical inputs.`);
      return {run, jobs: evidence.jobs};
    }
    if (evidence.encountered) return null;
  }
  return null;
}

module.exports = {trustedPushProof};
