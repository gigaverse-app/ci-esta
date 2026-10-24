const {execFileSync} = require('node:child_process');
const fs = require('node:fs');
const path = require('node:path');

async function hasContradiction(github, context, sha, event, branch) {
  const {data: current} = await github.rest.actions.getWorkflowRun({...context.repo, run_id:context.runId});
  const runs = await github.paginate(github.rest.actions.listWorkflowRuns, {
    ...context.repo, workflow_id:current.workflow_id, head_sha:sha, event, branch, per_page:100,
  });
  return runs.some(run => run.id !== context.runId && run.head_sha === sha &&
    run.status === 'completed' && run.conclusion !== 'success');
}

async function mergedPullRequest({github, context, sha, branch, attempt, core}) {
  if (attempt !== 1 || !/^[0-9a-f]{40}$/.test(sha || '') || !branch) return null;
  try {
    if (await hasContradiction(github, context, sha, 'push', branch)) return null;
    const listed = await github.paginate(github.rest.repos.listPullRequestsAssociatedWithCommit,
      {...context.repo, commit_sha:sha, per_page:100});
    const candidates = [];
    for (const item of listed) {
      const {data: pr} = await github.rest.pulls.get({...context.repo, pull_number:item.number});
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

async function proofTarget({github, context, core, actionPath, paths, sha, attempt, afterMerge, releaseVersion}) {
  const ordinary = {pr:context.payload.pull_request, sha, manifests:{}, releaseOnly:false};
  if (attempt !== 1 || !paths.length) return ordinary;
  const push = afterMerge && context.eventName === 'push' && context.ref?.startsWith('refs/heads/');
  if (push) ordinary.pr = await mergedPullRequest({github,context,core,sha,
    branch:context.ref.slice('refs/heads/'.length),attempt});
  const pr = ordinary.pr;
  if (releaseVersion && (context.eventName === 'pull_request' || push) &&
      pr?.head.repo.full_name === `${context.repo.owner}/${context.repo.repo}`) {
    try {
      const base = push ? execFileSync('git',['rev-parse',`${sha}^1`],{encoding:'utf8'}).trim() : pr.base.sha;
      const version = JSON.parse(execFileSync('python3', [path.join(actionPath,'release_version.py'),base,sha], {encoding:'utf8'}));
      if (!version.version_only || (!push && await hasContradiction(github,context,pr.head.sha,'pull_request',pr.head.ref))) return ordinary;
      const source = await mergedPullRequest({github,context,core,sha:base,branch:pr.base.ref,attempt});
      if (!source) return ordinary;
      const localAction = fs.realpathSync(path.resolve(actionPath,'../..')) === fs.realpathSync(process.cwd());
      return {pr:source,sha:base,manifests:localAction?version.manifests:{},releaseOnly:true};
    } catch (error) {
      core.warning(`Release version proof unavailable: ${error.message}; execute fresh validation.`);
    }
  }
  return ordinary;
}

module.exports = {mergedPullRequest, proofTarget};
