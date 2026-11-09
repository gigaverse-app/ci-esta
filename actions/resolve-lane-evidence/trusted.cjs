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
async function trustedPushProof({github, context, core, jobName, receipt, maxAgeHours = 24, cache = new Map()}) {
  const branch = context.payload.repository?.default_branch;
  if (!branch || !receipt) return null;
  const read = async (key, load) => {
    if (!cache.has(key)) cache.set(key, load());
    return cache.get(key);
  };
  const {data: current} = await read(`run:${context.runId}`, () =>
    github.rest.actions.getWorkflowRun({...context.repo, run_id: context.runId}));
  const oldest = Date.now() - maxAgeHours * 3600 * 1000;
  // Ask only for the window that can prove anything; the branch's whole history grows without bound.
  const since = new Date(oldest - 3600 * 1000).toISOString();
  const runs = await read(`push-runs:${current.workflow_id}:${branch}`, () =>
    github.paginate(github.rest.actions.listWorkflowRuns, {
      ...context.repo, workflow_id: current.workflow_id, branch, event: 'push', status: 'completed',
      created: `>=${since}`, per_page: 100,
    }));
  const candidates = runs
    .filter((run) => run.id !== context.runId && run.run_attempt === 1 && Date.parse(run.updated_at) >= oldest)
    .sort((a, b) => Date.parse(b.updated_at) - Date.parse(a.updated_at));
  for (const run of candidates) {
    const jobs = await read(`jobs:${run.id}`, () =>
      github.paginate(github.rest.actions.listJobsForWorkflowRun, {...context.repo, run_id: run.id, filter: 'latest', per_page: 100}));
    const job = jobs.find((candidate) => candidate.name === jobName &&
      (candidate.steps || []).some((step) => step.name === receipt));
    if (!job) continue;
    const step = job.steps.find((candidate) => candidate.name === receipt);
    if (job.conclusion === 'success' && step.conclusion === 'success') {
      core.info(`Default-branch run ${run.id} (${run.head_sha.slice(0, 7)}) proved '${jobName}' for identical inputs.`);
      return {run, jobs: [job]};
    }
    core.info(`Default-branch run ${run.id} (${run.head_sha.slice(0, 7)}) has '${jobName}' ${job.conclusion} for these inputs; executing fresh.`);
    return null;
  }
  return null;
}

module.exports = {trustedPushProof};
