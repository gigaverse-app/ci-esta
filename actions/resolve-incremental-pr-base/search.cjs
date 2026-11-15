// One invocation owns the evidence snapshot, its API reads and its failure state.
// This is the native GitHub API boundary shared by PR, lag-recovery and push proof.
// Positive verdicts remain lane-specific. Refusals are scoped to the job and
// receipt so a fallback source cannot erase a decision to execute.
const SESSION = Symbol('ci-esta evidence search');

function newestFirst(left, right) {
  return Date.parse(right.updated_at || right.created_at) - Date.parse(left.updated_at || left.created_at)
    || right.id - left.id;
}

function matchesJobPattern(name, pattern) {
  if (!pattern.includes('*')) return name === pattern || name.endsWith(` / ${pattern}`);
  const escaped = pattern.replace(/[.+?^${}()|[\]\\]/g, '\\$&').replace(/\*/g, '.*');
  return new RegExp(`^${escaped}$`).test(name);
}

function relevantRunIds(checks, currentRunId, patterns) {
  const ids = new Set();
  for (const check of checks) {
    // Older clients/tests may lack a name. Unknown metadata must not hide a
    // contradiction; fetch it. Real named unrelated jobs cannot prove this lane.
    if (check.name && !patterns.some(pattern => matchesJobPattern(check.name, pattern))) continue;
    const match = check.details_url?.match(/\/actions\/runs\/(\d+)/);
    if (match && Number(match[1]) !== currentRunId) ids.add(Number(match[1]));
  }
  return ids;
}

class EvidenceSearch {
  constructor(github, context, cache, nowMs) {
    this.nowMs = nowMs;
    this.github = github;
    this.context = context;
    this.cache = cache;
    this.stopped = null;
    this.requests = new Map();
    this.refusals = new Map();
  }

  refuse(job, receipt, reason, run = null) {
    const key = JSON.stringify([job, receipt]);
    const previous = this.refusals.get(key);
    // Unknown chronology cannot be superseded. Known contrary results establish
    // a temporal barrier: a later trusted pass of these inputs can still prove them.
    if (!previous || (previous.run && (!run || newestFirst(run, previous.run) < 0)))
      this.refusals.set(key, {reason, run});
  }
  canSearch(job, receipt) {
    const refusal = this.refusals.get(JSON.stringify([job, receipt]));
    return !this.stopped && (!refusal || Boolean(refusal.run));
  }
  allows(job, receipt, run) {
    const refusal = this.refusals.get(JSON.stringify([job, receipt]));
    return this.canSearch(job, receipt) && (!refusal || newestFirst(run, refusal.run) < 0);
  }

  audit(core, source, job) {
    core.info(`Evidence discovery ${JSON.stringify({source, job, requests: Object.fromEntries(this.requests),
      stopped: Boolean(this.stopped), refusals: [...this.refusals.values()].map(({reason, run}) => ({reason, run: run?.id}))})}`);
  }

  async read(key, load) {
    if (this.stopped) throw this.stopped;
    if (!this.cache.has(key)) {
      this.cache.set(key, Promise.resolve().then(load));
    }
    return this.cache.get(key);
  }

  async request(kind, method, args) {
    if (this.stopped) throw this.stopped;
    this.requests.set(kind, (this.requests.get(kind) || 0) + 1);
    try {
      return await method({...this.context.repo, ...args});
    } catch (error) {
      // Permission denial and throttling both make further optional discovery unusable.
      if ([403, 429].includes(error.status)) this.stopped = error;
      throw error;
    }
  }

  async collection(kind, method, args, field) {
    return this.read(`${kind}:${JSON.stringify(args)}`, async () => {
      const items = [];
      const seen = new Set();
      for (let page = 1; ; page += 1) {
        const response = await this.request(kind, method, {...args, per_page: 100, page});
        // GitHub caps filtered workflow-run searches at 1,000 results. More
        // pages cannot recover the omitted chronology, so do not request them.
        if (kind === 'runs' && response.data.total_count > 1000)
          throw new Error('Workflow search exceeds GitHub\'s 1,000-result completeness limit');
        const batch = field ? response.data[field] : response.data;
        // Overlapping/changing pagination cannot establish a complete chronology.
        // Never admit an old success from a silently truncated index.
        for (const item of batch) {
          if (seen.has(item.id)) throw new Error(`Incomplete ${kind} index: repeated item ${item.id}`);
          seen.add(item.id);
          items.push(item);
        }
        const next = response.headers?.link?.includes('rel="next"');
        const total = response.data.total_count;
        if (!next && (Number.isSafeInteger(total) ? items.length === total : batch.length < 100)) return items;
        if (!batch.length || (Number.isSafeInteger(total) && items.length > total))
          throw new Error(`Incomplete ${kind} index`);
      }
    });
  }

  run(id) {
    return this.read(`run:${id}`, () => this.request('run', this.github.rest.actions.getWorkflowRun, {run_id: id}));
  }
  runs(args) {
    return this.collection('runs', this.github.rest.actions.listWorkflowRuns, args, 'workflow_runs');
  }
  pullRequests(sha) {
    return this.collection('pull-requests', this.github.rest.repos.listPullRequestsAssociatedWithCommit,
      {commit_sha: sha});
  }
  pullRequest(number) {
    return this.read(`pull-request:${number}`, () => this.request('pull-request', this.github.rest.pulls.get,
      {pull_number: number}));
  }
  async jobs(id, attempt) {
    const jobs = await this.collection('jobs', this.github.rest.actions.listJobsForWorkflowRun,
      {run_id: id, filter: 'latest'}, 'jobs');
    if (attempt !== undefined && jobs.some(job => job.run_attempt !== undefined && job.run_attempt !== attempt))
      throw new Error(`Run ${id} changed attempts during evidence discovery`);
    return jobs;
  }
  checks(sha) {
    return this.collection('checks', this.github.rest.checks.listForRef, {ref: sha}, 'check_runs');
  }
  statuses(sha) {
    return this.collection('statuses', this.github.rest.repos.listCommitStatusesForRef, {ref: sha});
  }
  comparison(base, head) {
    const basehead = `${base}...${head}`;
    return this.read(`comparison:${basehead}`, () => this.request('comparison',
      this.github.rest.repos.compareCommitsWithBasehead, {basehead}));
  }
  commit(sha) {
    return this.read(`commit:${sha}`, () => this.request('commit', this.github.rest.repos.getCommit, {ref: sha}));
  }
}

function evidenceSearch(github, context, cache = new Map(), nowMs = Date.now()) {
  if (!cache.has(SESSION)) cache.set(SESSION, new EvidenceSearch(github, context, cache, nowMs));
  const search = cache.get(SESSION);
  if (search.github !== github || search.context.runId !== context.runId ||
      search.context.repo.owner !== context.repo.owner || search.context.repo.repo !== context.repo.repo)
    throw new Error('An evidence snapshot belongs to one repository, client and workflow invocation');
  return search;
}

module.exports = {evidenceSearch, matchesJobPattern, relevantRunIds, newestFirst};
