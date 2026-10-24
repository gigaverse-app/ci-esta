const SHA = /^[0-9a-f]{40}$/;

async function resolveScheduledBase({ github, context, core, headSha, branch,
  evidenceJob, evidenceStep, maxAgeHours = 168, nowMs = Date.now() }) {
  const fallback = (reason) => {
    core.warning(`Scheduled selection requires full execution: ${reason}`);
    return { baseSha: '', runId: '', reason };
  };
  if (!SHA.test(headSha) || !branch || !evidenceJob || !evidenceStep ||
      !Number.isFinite(maxAgeHours) || maxAgeHours <= 0) return fallback('invalid inputs');
  try {
    const { data: current } = await github.rest.actions.getWorkflowRun({ ...context.repo, run_id: context.runId });
    const { data } = await github.rest.actions.listWorkflowRuns({
      ...context.repo, workflow_id: current.workflow_id, branch, event: 'schedule', per_page: 100,
    });
    if (!Array.isArray(data.workflow_runs)) return fallback('unreadable history');
    // Bound API work. An older proof outside this window only costs a full run.
    const runs = data.workflow_runs.filter((run) => run.id !== context.runId &&
      run.workflow_id === current.workflow_id && run.head_branch === branch && run.event === 'schedule')
      .sort((a, b) => b.id - a.id);
    for (const run of runs.slice(0, 20)) {
      // A newer failed/cancelled/incomplete run must be retried, even at the same SHA.
      if (run.status !== 'completed' || run.conclusion !== 'success') return fallback('newer schedule did not pass');
      const age = nowMs - Date.parse(run.created_at);
      if (!SHA.test(run.head_sha) || !Number.isFinite(age) || age < 0 || age > maxAgeHours * 3600000) {
        return fallback('stale or invalid source run');
      }
      const jobs = await github.paginate(github.rest.actions.listJobsForWorkflowRun, {
        ...context.repo, run_id: run.id, filter: 'latest', per_page: 100,
      });
      // A green no-change night never renews the proof's age or advances the base.
      if (!jobs.some((job) => job.name === evidenceJob && job.conclusion === 'success' &&
          job.steps?.some((step) => step.name === evidenceStep && step.conclusion === 'success'))) continue;
      const { data: comparison } = await github.rest.repos.compareCommitsWithBasehead({
        ...context.repo, basehead: `${run.head_sha}...${headSha}`,
      });
      if (!['ahead', 'identical'].includes(comparison.status)) return fallback('source is not an ancestor');
      core.info(`Scheduled baseline: run ${run.id}, revision ${run.head_sha}`);
      return { baseSha: run.head_sha, runId: String(run.id), reason: 'successful scheduled execution' };
    }
    return fallback('no executed scheduled proof');
  } catch (error) {
    return fallback(`history unavailable: ${error.message}`);
  }
}

module.exports = { resolveScheduledBase };
