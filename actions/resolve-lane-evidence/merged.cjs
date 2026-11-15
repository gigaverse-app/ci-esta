const {evidenceSearch} = require('../resolve-incremental-pr-base/search.cjs');
const {execFileSync} = require('node:child_process');
const path = require('node:path');

async function hasContradiction(search, context, sha, event, branch) {
  const {data: current} = await search.run(context.runId);
  const runs = await search.runs({workflow_id: current.workflow_id, head_sha: sha, event, branch});
  return runs.some(run => run.id !== context.runId && run.head_sha === sha &&
    run.status === 'completed' && run.conclusion !== 'success');
}

async function mergedPullRequest({github, context, sha, branch, attempt, core, evidenceCache = new Map()}) {
  if (attempt !== 1 || !/^[0-9a-f]{40}$/.test(sha || '') || !branch) return null;
  try {
    const search = evidenceSearch(github, context, evidenceCache);
    if (await hasContradiction(search, context, sha, 'push', branch)) return null;
    const listed = await search.pullRequests(sha);
    const candidates = [];
    for (const item of listed) {
      const {data: pr} = await search.pullRequest(item.number);
      const repository = `${context.repo.owner}/${context.repo.repo}`;
      if (pr.merged === true && pr.merge_commit_sha === sha && pr.base?.ref === branch &&
          pr.base.repo?.full_name === repository && pr.head?.repo?.full_name === repository) candidates.push(pr);
    }
    return candidates.length === 1 ? candidates[0] : null;
  } catch (error) {
    core.warning(`Merged PR evidence unavailable: ${error.message}; execute fresh validation.`);
    return null;
  }
}

async function proofTarget({github, context, core, actionPath, paths, sha, attempt, afterMerge, releaseVersion, evidenceCache = new Map()}) {
  const ordinary = {pr:context.payload.pull_request, sha, releaseOnly:false};
  if (attempt !== 1 || !paths.length) return ordinary;
  const push = afterMerge && context.eventName === 'push' && context.ref?.startsWith('refs/heads/');
  if (push) ordinary.pr = await mergedPullRequest({github,context,core,sha,
    branch:context.ref.slice('refs/heads/'.length),attempt,evidenceCache});
  const pr = ordinary.pr;
  if (releaseVersion && (context.eventName === 'pull_request' || push) &&
      pr?.head.repo.full_name === `${context.repo.owner}/${context.repo.repo}`) {
    try {
      const base = push ? execFileSync('git',['rev-parse',`${sha}^1`],{encoding:'utf8'}).trim() : pr.base.sha;
      const version = JSON.parse(execFileSync('python3', [path.join(actionPath,'release_version.py'),base,sha], {encoding:'utf8'}));
      if (!version.version_only || (!push && await hasContradiction(evidenceSearch(github,context,evidenceCache),context,pr.head.sha,'pull_request',pr.head.ref))) return ordinary;
      const source = await mergedPullRequest({github,context,core,sha:base,branch:pr.base.ref,attempt,evidenceCache});
      if (!source) return ordinary;
      return {pr:source,sha:base,releaseOnly:true};
    } catch (error) {
      core.warning(`Release version proof unavailable: ${error.message}; execute fresh validation.`);
    }
  }
  return ordinary;
}

module.exports = {mergedPullRequest, proofTarget};
