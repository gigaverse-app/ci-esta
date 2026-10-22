// Coverage admission is independent of test selection: even a full PR suite
// does not collect coverage unless explicitly requested.
module.exports = async function coveragePolicy({github, context, core, explicit = false}) {
  const marker = `coverage-main-${context.sha}`;
  const requested = explicit || (context.eventName === 'pull_request' &&
    context.payload.pull_request.labels.some(label => label.name === 'run-coverage'));
  let enabled = requested;
  let reason = requested ? 'Explicit coverage request' : 'Coverage disabled by default';
  if (!requested && context.eventName === 'schedule' && context.ref === 'refs/heads/main') {
    // The caller schedules once weekly. API failure may spend that one attempt,
    // but must never turn ordinary PRs or pushes into automatic coverage runs.
    enabled = true;
    reason = 'Weekly main coverage';
    try {
      const {data} = await github.rest.actions.listArtifactsForRepo({
        ...context.repo, name: marker, per_page: 100,
      });
      if (data.artifacts.some(artifact => !artifact.expired)) {
        enabled = false;
        reason = 'This main commit already has coverage';
      }
    } catch (error) {
      core.warning(`Coverage marker unavailable: ${error.message}`);
    }
  }
  core.setOutput('enabled', enabled);
  core.setOutput('marker', marker);
  core.setOutput('reason', reason);
  core.info(`Coverage: ${enabled}; ${reason}`);
};
