const { inventoryIdentity, validationReceipt } = require('../resolve-lane-evidence/inputs.cjs');
const { resolveIncrementalPrBase } = require('../resolve-incremental-pr-base/resolve.cjs');

// Inventory owns its evidence. A source scan's incremental base cannot prove that
// dependencies were scanned successfully. Explicit requests always run afresh.
async function resolveInventory({ github, shared, context, core, actionPath, paths, jobName, mode }) {
  const pr = context.payload.pull_request;
  if (mode !== 'pull_request' || !pr || !jobName) return null;
  try {
    const [head, base] = await Promise.all([
      inventoryIdentity(github, shared, context.repo, pr.head.sha, paths),
      inventoryIdentity(github, shared, context.repo, pr.base.sha, paths),
    ]);
    const receipt = validationReceipt(actionPath, head);
    if (head === base) return { changed: false, receipt };
    if (Number(process.env.GITHUB_RUN_ATTEMPT) !== 1) return { changed: true, receipt };
    const proof = await resolveIncrementalPrBase({
      github, context, core, fallbackBaseSha: pr.base.sha, headSha: pr.head.sha,
      headRef: pr.head.ref, pullRequestNumber: pr.number, evidenceJobName: jobName,
      evidenceStepName: receipt, sameHeadOnly: true, maxAgeHours: 24, conservativeFailures: true,
    });
    return { changed: !proof.reused, receipt };
  } catch (error) {
    core.warning(`Inventory evidence unavailable (${error.message}); requiring a fresh scan.`);
    return { changed: true, receipt: '' };
  }
}
module.exports = { resolveInventory };
