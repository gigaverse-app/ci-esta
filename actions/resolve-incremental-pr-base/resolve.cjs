const SHA_PATTERN = /^[0-9a-f]{40}$/;
// GitHub masks secret values everywhere in a job, step names included: a job holding a secret
// "33" shows a receipt as ...eb5***1edbb... (backend-common#216's CI drill). Masking hides
// characters and never changes the rest, so a masked receipt still proves the lane when every
// visible segment matches, in order, and no more than this many characters are hidden.
const MAX_MASKED_RECEIPT_CHARS = 16;

// The workflow runs a commit's check runs belong to, other than this run.
function runIdsFromCheckRuns(checkRuns, currentRunId) {
  const runIds = new Set();
  for (const checkRun of checkRuns) {
    const match = checkRun.details_url?.match(/\/actions\/runs\/(\d+)/);
    if (match && Number(match[1]) !== currentRunId) runIds.add(Number(match[1]));
  }
  return runIds;
}

function receiptMatches(name, receipt) {
  if (name === receipt) return true;
  if (!receipt || !name.includes("***")) return false;
  const parts = name.split("***");
  const hidden = receipt.length - parts.join("").length;
  const last = parts[parts.length - 1];
  if (hidden <= 0 || hidden > MAX_MASKED_RECEIPT_CHARS) return false;
  if (!receipt.startsWith(parts[0]) || !receipt.endsWith(last)) return false;
  let at = parts[0].length;
  for (const part of parts.slice(1, -1)) {
    const found = receipt.indexOf(part, at);
    if (found < 0) return false;
    at = found + part.length;
  }
  return receipt.length - last.length >= at;
}
const HOUR_MS = 60 * 60 * 1000;
const MAX_ANCESTOR_HEADS = 10;

async function resolveIncrementalPrBase({
  github,
  context,
  core,
  fallbackBaseSha,
  headSha,
  headRef,
  pullRequestNumber,
  evidenceJobName,
  evidenceStepName = "",
  pytestEvidence,
  validationEvidence = false,
  testedMergeStepPrefix = "",
  sameHeadOnly = false,
  conservativeFailures = false,
  cancelledRunEvidenceJobPatterns = [],
  maxAgeHours = 168,
  nowMs = Date.now(),
  evidenceCache = new Map(),
  onReuse,
}) {
  // One planning invocation may evaluate several lanes. Share only raw API evidence,
  // never verdicts: each lane still enforces its own receipt and newer-failure revocation.
  // The caller owns this snapshot; it must never survive into another planning invocation.
  const readEvidence = async (key, read) => {
    // Cache the promise before awaiting it, including rejection. A slow API outage
    // must not repeat once per lane; each caller still handles uncertainty itself.
    if (!evidenceCache.has(key)) evidenceCache.set(key, Promise.resolve().then(read));
    return evidenceCache.get(key);
  };
  const fallback = { baseSha: fallbackBaseSha, reused: false };
  if (
    !SHA_PATTERN.test(fallbackBaseSha) ||
    !SHA_PATTERN.test(headSha) ||
    !headRef ||
    !evidenceJobName ||
    (validationEvidence && (!evidenceStepName || sameHeadOnly || pytestEvidence)) ||
    (sameHeadOnly && (!evidenceStepName || pytestEvidence)) ||
    (testedMergeStepPrefix && !validationEvidence) ||
    !Number.isInteger(pullRequestNumber) ||
    pullRequestNumber <= 0 ||
    !Number.isFinite(maxAgeHours) ||
    maxAgeHours <= 0
  ) {
    core.warning("Incremental PR inputs are invalid; falling back to the pull request base.");
    return fallback;
  }

  try {
    const { data: currentRun } = await readEvidence(`run:${context.runId}`, () => github.rest.actions.getWorkflowRun({
      owner: context.repo.owner,
      repo: context.repo.repo,
      run_id: context.runId,
    }));
    const oldestReusableMs = nowMs - maxAgeHours * HOUR_MS;
    const reusableConclusions = pytestEvidence || sameHeadOnly || validationEvidence ? ["success", "failure", "cancelled"] : ["success", "cancelled"];
    // Every reason a listed run cannot serve as evidence. An empty list is the only
    // admission; the reasons are logged, because a silent fallback hid for weeks that
    // same-head reuse never fired.
    const recoveredOwners = new Set();
    const unverifiedOwners = new Set();
    const rejectionReasons = (run) => {
      const completedMs = Date.parse(run.updated_at || run.created_at || "");
      const reasons = [];
      if (run.workflow_id !== currentRun.workflow_id) reasons.push("another workflow");
      if (run.status !== "completed") reasons.push(`status ${run.status}`);
      else if (!validationEvidence && !pytestEvidence && !sameHeadOnly && !reusableConclusions.includes(run.conclusion)) reasons.push(`conclusion ${run.conclusion}`);
      // Receipt-bound lanes admit any head of this PR: the receipt names the tested inputs, so
      // an earlier head whose run carries the same receipt tested the same thing (a retag that
      // only moves a first-party pin to an identical tree). A different receipt never matches.
      if (!SHA_PATTERN.test(run.head_sha || "")) reasons.push("no head SHA");
      // Pytest proof needs a first attempt; same-head reruns are admitted only so
      // that their failures can revoke older same-head evidence.
      if (pytestEvidence && run.run_attempt !== 1 && run.head_sha !== headSha) reasons.push(`attempt ${run.run_attempt}`);
      if (!recoveredOwners.has(run.id) && !(run.pull_requests || []).some((pullRequest) => pullRequest.number === pullRequestNumber)) {
        reasons.push(`not associated with PR #${pullRequestNumber}`);
      }
      if (!Number.isFinite(completedMs)) reasons.push("no completion time");
      else if (completedMs < oldestReusableMs) reasons.push(`completed before ${new Date(oldestReusableMs).toISOString()}`);
      return reasons;
    };
    const isReusableRun = (run) => run.id !== context.runId && rejectionReasons(run).length === 0;
    const recoverOwner = async (run) => {
      if (run.id === context.runId || (run.pull_requests || []).length ||
          run.event !== "pull_request" || run.head_branch !== headRef) return;
      const reasons = rejectionReasons(run);
      if (reasons.length !== 1 || reasons[0] !== `not associated with PR #${pullRequestNumber}`) return;
      unverifiedOwners.add(run.id);
      try {
        const jobs = await readEvidence(`jobs:${run.id}`, () => github.paginate(github.rest.actions.listJobsForWorkflowRun, {
          ...context.repo, run_id: run.id, filter: "latest", per_page: 100,
        }));
        // GitHub may omit pull_requests even while a PR is open. A successful execution
        // marker binds this run to its actual PR and head; a matching branch never suffices.
        const owner = `PR evidence #${pullRequestNumber} head ${run.head_sha}`;
        if (jobs.some((job) => (job.steps || []).some((step) => step.name === owner && step.conclusion === "success"))) {
          recoveredOwners.add(run.id);
          unverifiedOwners.delete(run.id);
          core.info(`Recovered PR #${pullRequestNumber} ownership for run ${run.id} from its execution marker.`);
        }
      } catch (error) {
        core.warning(`Could not establish PR ownership for run ${run.id} (${error.message}); retaining validation.`);
      }
    };
    const sameHeadFromCheckRuns = async () => {
      let checkRuns;
      try {
        checkRuns = await readEvidence(`checks:${headSha}`, () => github.paginate(github.rest.checks.listForRef, {
          owner: context.repo.owner, repo: context.repo.repo, ref: headSha, per_page: 100,
        }));
      } catch (error) {
        core.warning(`Could not inspect checks on ${headSha} (${error.message}); falling back.`);
        return null;
      }
      const runs = [];
      for (const runId of runIdsFromCheckRuns(checkRuns, context.runId)) {
        let run;
        try {
          ({ data: run } = await readEvidence(`run:${runId}`, () => github.rest.actions.getWorkflowRun({
            owner: context.repo.owner, repo: context.repo.repo, run_id: runId,
          })));
        } catch (error) {
          core.warning(`Could not inspect same-head run ${runId} (${error.message}); retaining validation.`);
          return null;
        }
        runs.push(run);
      }
      // Check-run transport order cannot let an older success hide newer contradictory proof.
      for (const run of runs.sort(newestFirst)) {
        await recoverOwner(run);
        if (unverifiedOwners.has(run.id)) return null;
        const reasons = [...rejectionReasons(run), ...(run.head_sha === headSha ? [] : ["different head"])];
        if (reasons.length) {
          reportRejection(run, reasons);
          continue;
        }
        const succeeded = await hasSuccessfulEvidence(run);
        if (contradictedSameHeadEvidence) return null;
        if (succeeded) return admittedReuse(run);
      }
      return null;
    };
    const reportRejection = (run, reasons) =>
      core.info(`Candidate run ${run.id} (${(run.head_sha || "").slice(0, 7)}) rejected: ${reasons.join("; ")}`);
    const newestFirst = (left, right) => {
      const leftMs = Date.parse(left.updated_at || left.created_at);
      const rightMs = Date.parse(right.updated_at || right.created_at);
      return rightMs - leftMs || right.id - left.id;
    };
    const evidenceByRunId = new Map();
    const testedMergeByRunId = new Map();
    let contradictedSameHeadEvidence = false;
    const outsideFallbackBaseBySha = new Map();
    // Runs the listing returned in their final state: already judged, never fetched again.
    const listedCompleted = new Set();
    const matchesJobPattern = (jobName, pattern) => {
      if (!pattern.includes("*")) {
        return jobName === pattern || jobName.endsWith(` / ${pattern}`);
      }
      const escaped = pattern.replace(/[.+?^${}()|[\]\\]/g, "\\$&").replace(/\*/g, ".*");
      return new RegExp(`^${escaped}$`).test(jobName);
    };
    const admittedReuse = async (run) => {
      // Observability is downstream of the verdict. A broken sink cannot revoke
      // proof or admit work which the resolver would otherwise execute.
      if (sameHeadOnly && onReuse) {
        try {
          const jobs = await evidenceCache.get(`jobs:${run.id}`);
          await onReuse({run, jobs: (jobs || []).filter(job =>
            matchesJobPattern(job.name, evidenceJobName) && job.conclusion === 'success' &&
            (job.steps || []).some(step => receiptMatches(step.name, evidenceStepName) && step.conclusion === 'success'))});
        } catch (error) {
          core.warning(`Reuse measurements unavailable: ${error.message}`);
        }
      }
      return {baseSha: headSha, reused: true};
    };
    const hasSuccessfulEvidence = async (run) => {
      if (evidenceByRunId.has(run.id)) return evidenceByRunId.get(run.id);
      try {
        if (pytestEvidence?.successStatusContext) {
          const statuses = await github.paginate(github.rest.repos.listCommitStatusesForRef, {
            ...context.repo, ref: run.head_sha, per_page: 100,
          });
          const gate = statuses.find((status) => status.context === pytestEvidence.successStatusContext);
          const runUrl = `${context.serverUrl}/${context.repo.owner}/${context.repo.repo}/actions/runs/${run.id}`;
          // Bind the gate to this attempt, not another workflow on the same SHA.
          // Every attempt of a run shares its URL, so only a first attempt proves.
          if (run.run_attempt === 1 && gate?.state === "success" && gate.target_url === runUrl &&
              /^Default gate passed; base=[0-9a-f]{40}$/.test(gate.description)) {
            const proof = { baseSha: run.head_sha, reused: true };
            evidenceByRunId.set(run.id, proof);
            return proof;
          }
        }
        const jobs = await readEvidence(`jobs:${run.id}`, () => github.paginate(github.rest.actions.listJobsForWorkflowRun, {
          owner: context.repo.owner,
          repo: context.repo.repo,
          run_id: run.id,
          filter: "latest",
          per_page: 100,
        }));
        if (pytestEvidence) {
          const plan = jobs.find((job) => matchesJobPattern(job.name, pytestEvidence.planJobName));
          const test = jobs.find((job) => matchesJobPattern(job.name, evidenceJobName));
          const complete = test?.steps?.some((step) =>
            step.name === pytestEvidence.completionStepName && step.conclusion === "success");
          // Independent pytest proof never asserts that a security gate passed.
          // Failed proof only proposes a candidate: artifact validation + union
          // of EVERY unresolved failure is required before adopting its base.
          // Enforcement point: a pytest failure of THIS tree, including from an explicit
          // rerun, revokes every same-head proof. It never resurrects an older green run,
          // and never becomes a failure candidate: with an empty delta that path would
          // re-run only the failed files, so one flaky pass would turn a red commit green.
          if (run.head_sha === headSha && test?.conclusion === "failure") contradictedSameHeadEvidence = true;
          let proof = false;
          if (plan?.conclusion === "success" && complete && run.run_attempt === 1) {
            if (test.conclusion === "success") proof = { baseSha: run.head_sha, reused: true };
            const shards = test.name.match(/\b([1-9][0-9]*) concurrent shards\b/);
            if (test.conclusion === "failure" && shards) proof = {
              ...fallback, failedSha: run.head_sha, failedRunId: run.id, failedShardCount: Number(shards[1]),
            };
          }
          evidenceByRunId.set(run.id, proof);
          return proof;
        }
        // A later failure is new information, including from an explicit
        // rerun. Never reach back past it to resurrect an older green result.
        // A skipped completion step still names the inputs of a failed job. It
        // cannot prove success, but must revoke an older pass for those inputs.
        // Inventories use conservativeFailures: mutable advisory/image inputs can
        // change the verdict, and even a failure with an unavailable receipt
        // requires a fresh scan rather than resurrecting earlier success.
        if (sameHeadOnly && jobs.some((job) =>
          matchesJobPattern(job.name, evidenceJobName) && job.conclusion === 'failure' &&
          (conservativeFailures || run.head_sha === headSha ||
            (job.steps || []).some((step) => receiptMatches(step.name, evidenceStepName))))) {
          contradictedSameHeadEvidence = true;
        }
        const evidenceJobs = jobs.filter((job) => matchesJobPattern(job.name, evidenceJobName));
        const primaryEvidenceSucceeded = (!sameHeadOnly || run.run_attempt === 1) && evidenceJobs.some(
          (job) => job.conclusion === "success" &&
            (!evidenceStepName || (job.steps || []).some(
              (step) => receiptMatches(step.name, evidenceStepName) && step.conclusion === "success",
            )),
        );
        // A cancelled workflow can still finish already-admitted jobs. Reuse
        // it only when every scanner pattern is positively proven successful;
        // a missing, skipped, failed, or cancelled scanner fails open.
        const cancelledEvidenceSucceeded =
          sameHeadOnly || run.conclusion !== "cancelled" ||
          (cancelledRunEvidenceJobPatterns.length > 0 &&
            cancelledRunEvidenceJobPatterns.every((pattern) =>
              jobs.some(
                (job) => matchesJobPattern(job.name, pattern) && job.conclusion === "success",
              ),
            ));
        let proven = primaryEvidenceSucceeded && cancelledEvidenceSucceeded;
        if (proven && testedMergeStepPrefix) {
          const merges = evidenceJobs.filter(job => job.conclusion === "success" &&
            (job.steps || []).some(step => receiptMatches(step.name, evidenceStepName) && step.conclusion === "success"))
            .flatMap(job => (job.steps || []).filter(step =>
              step.conclusion === "success" && step.name.startsWith(testedMergeStepPrefix))
              .map(step => step.name.slice(testedMergeStepPrefix.length)));
          // Only the completed evidence job can name the exact tested merge; masked SHAs cannot identify it.
          proven = merges.length === 1 && SHA_PATTERN.test(merges[0]);
          if (proven) testedMergeByRunId.set(run.id, merges[0]);
          else reportRejection(run, ["missing or ambiguous tested merge identity"]);
        }
        if (!proven) {
          const reasons = [];
          if (sameHeadOnly && run.run_attempt !== 1) reasons.push(`attempt ${run.run_attempt} (reruns reproduce, never prove)`);
          if (!evidenceJobs.length) reasons.push(`no job '${evidenceJobName}'`);
          for (const job of evidenceJobs.filter((candidate) => candidate.conclusion !== "success")) {
            reasons.push(`'${job.name}' concluded ${job.conclusion}`);
          }
          if (evidenceStepName && evidenceJobs.some((job) => job.conclusion === "success") && !evidenceJobs.some(
            (job) => (job.steps || []).some((step) => receiptMatches(step.name, evidenceStepName) && step.conclusion === "success"),
          )) {
            reasons.push(`no successful step '${evidenceStepName}'`);
          }
          if (!cancelledEvidenceSucceeded) reasons.push("cancelled run lacks proof from every scanner");
          reportRejection(run, reasons);
        }
        evidenceByRunId.set(run.id, proven);
        return proven;
      } catch (error) {
        core.warning(`Could not verify evidence job for run ${run.id} (${error.message}); continuing.`);
        if ((sameHeadOnly && conservativeFailures) || ((sameHeadOnly || pytestEvidence) && run.head_sha === headSha))
          contradictedSameHeadEvidence = true;
        evidenceByRunId.set(run.id, false);
        return false;
      }
    };
    const isOutsideFallbackBase = async (candidateSha) => {
      if (outsideFallbackBaseBySha.has(candidateSha)) {
        return outsideFallbackBaseBySha.get(candidateSha);
      }
      try {
        const { data: comparison } = await github.rest.repos.compareCommitsWithBasehead({
          owner: context.repo.owner,
          repo: context.repo.repo,
          basehead: `${candidateSha}...${fallbackBaseSha}`,
        });
        const outsideBase = !["ahead", "identical"].includes(comparison.status);
        if (!outsideBase) {
          core.info(
            `Ignoring successful ${candidateSha}: it is already contained in the current pull request base.`,
          );
        }
        outsideFallbackBaseBySha.set(candidateSha, outsideBase);
        return outsideBase;
      } catch (error) {
        core.warning(
          `Could not verify whether successful run head ${candidateSha} is already in the pull request base (${error.message}); continuing.`,
        );
        outsideFallbackBaseBySha.set(candidateSha, false);
        return false;
      }
    };

    // The indexed path is normally one list + one compare call. Sorting here
    // is an enforcement point: never trust transport ordering for reuse.
    try {
      const indexedRuns = await readEvidence(`runs:${currentRun.workflow_id}:${headRef}`, () => github.paginate(github.rest.actions.listWorkflowRuns, {
        owner: context.repo.owner,
        repo: context.repo.repo,
        workflow_id: currentRun.workflow_id,
        event: "pull_request",
        branch: headRef,
        per_page: 100,
      }));
      const others = indexedRuns.filter((run) => run.id !== context.runId).sort(newestFirst);
      await Promise.all(others.map(recoverOwner));
      for (const run of others) if (run.status === "completed") listedCompleted.add(run.id);
      for (const run of others.slice(0, 20)) {
        const reasons = rejectionReasons(run);
        if (reasons.length) reportRejection(run, reasons);
      }
      const candidates = others.filter(run => isReusableRun(run) || ((validationEvidence || sameHeadOnly || pytestEvidence) && unverifiedOwners.has(run.id)));
      for (const candidate of candidates) {
        // An unverified newer owner cannot disappear and expose an older validation success.
        if (unverifiedOwners.has(candidate.id)) {
          core.info("Unverified PR ownership prevents advancing the selection base.");
          return fallback;
        }
        if (validationEvidence && candidate.conclusion !== "success") {
          core.info("Newer unsuccessful validation prevents advancing the selection base.");
          return fallback;
        }
        const succeeded = await hasSuccessfulEvidence(candidate);
        if (sameHeadOnly && contradictedSameHeadEvidence) return fallback;
        // Revoked same-head pytest evidence leaves ancestor proof, as before same-head reuse.
        if (pytestEvidence && contradictedSameHeadEvidence && candidate.head_sha === headSha) continue;
        if (!succeeded && validationEvidence) return fallback;
        if (!succeeded) continue;
        // Exact-head lanes require their own successful receipt naming the
        // tested merge SHA. No ancestor or overall workflow result substitutes.
        if (sameHeadOnly) return admittedReuse(candidate);
        // GitHub dynamically associates historical same-branch runs with a
        // newly opened PR. A run whose head has since landed in the base is
        // evidence for the previous PR, not for this recycled branch.
        if (!(await isOutsideFallbackBase(candidate.head_sha))) continue;
        try {
          const { data: comparison } = await github.rest.repos.compareCommitsWithBasehead({
            owner: context.repo.owner,
            repo: context.repo.repo,
            basehead: `${candidate.head_sha}...${headSha}`,
          });
          if (["ahead", "identical"].includes(comparison.status)) {
            core.info(
              `Validated evidence candidate ${candidate.head_sha} from run ${candidate.id} for incremental PR selection.`,
            );
            return pytestEvidence ? evidenceByRunId.get(candidate.id) : {
              baseSha: candidate.head_sha, reused: true,
              ...(testedMergeStepPrefix ? { testedMergeSha: testedMergeByRunId.get(candidate.id) } : {}),
            };
          }
        } catch (error) {
          core.warning(
            `Could not verify whether successful run ${candidate.id} is an ancestor (${error.message}); continuing.`,
          );
        }
      }
    } catch (error) {
      core.warning(`Could not list prior workflow runs (${error.message}); trying previous-head checks.`);
    }

    if (validationEvidence) return fallback;

    if (sameHeadOnly) {
      // Enforcement point for listing lag: the run listing can omit a just-completed run
      // (backend-common#216's drill: one lane of a plan found no candidate while later lanes
      // of the same plan did), but the head commit's own check runs name that run directly.
      const found = await sameHeadFromCheckRuns();
      if (found) return found;
      core.info(
        `No completed run of this workflow on ${headSha.slice(0, 7)} proved '${evidenceJobName}' for PR #${pullRequestNumber}.`,
      );
      return fallback;
    }

    // GitHub's workflow index can lag behind a completed run. Check runs on
    // recent first-parent ancestors expose their workflow run IDs immediately.
    // Inspect one ancestor at a time and return as soon as proof is found; this
    // bounds the common rapid-push path to two small API calls.
    let ancestorSha = headSha;
    for (let depth = 0; depth < MAX_ANCESTOR_HEADS; depth += 1) {
      let firstParentSha;
      try {
        const { data: commit } = await github.rest.repos.getCommit({
          owner: context.repo.owner,
          repo: context.repo.repo,
          ref: ancestorSha,
        });
        firstParentSha = commit.parents[0]?.sha;
        if (
          !SHA_PATTERN.test(firstParentSha || "") ||
          firstParentSha === ancestorSha ||
          firstParentSha === fallbackBaseSha
        ) {
          break;
        }
      } catch (error) {
        core.warning(`Could not walk ancestors from ${ancestorSha} (${error.message}); falling back.`);
        break;
      }
      try {
        const { data: checkResponse } = await github.rest.checks.listForRef({
          owner: context.repo.owner,
          repo: context.repo.repo,
          ref: firstParentSha,
          per_page: 100,
        });
        const runIds = runIdsFromCheckRuns(checkResponse.check_runs, context.runId);
        // Enforcement point: the walk exists only for runs the listing has not caught up with,
        // and lag hides only the newest runs. Once an ancestor names a run the listing already
        // returned completed, that run was judged above and every older ancestor's run is
        // older still, so it was listed too. Walking on re-fetched every run of every workflow
        // on ten ancestors (31s per backend plan job) for proof the listing had already refused.
        if ([...runIds].some((runId) => listedCompleted.has(runId))) {
          core.info(`Ancestor ${firstParentSha.slice(0, 7)} was already listed; no older run can be missing.`);
          break;
        }
        let inspected = 0;
        let ownRun = false;
        for (const runId of runIds) {
          try {
            const { data: run } = await readEvidence(`run:${runId}`, () => github.rest.actions.getWorkflowRun({
              owner: context.repo.owner,
              repo: context.repo.repo,
              run_id: runId,
            }));
            inspected += 1;
            await recoverOwner(run);
            if (recoveredOwners.has(run.id) || (run.pull_requests || []).some((pullRequest) => pullRequest.number === pullRequestNumber)) {
              ownRun = true;
            }
            if (
              run.head_sha === firstParentSha &&
              isReusableRun(run) &&
              (await hasSuccessfulEvidence(run)) &&
              (await isOutsideFallbackBase(run.head_sha))
            ) {
              core.info(
                `Validated evidence candidate ${run.head_sha} from run ${run.id} for incremental PR selection.`,
              );
              return pytestEvidence ? evidenceByRunId.get(run.id) : { baseSha: run.head_sha, reused: true };
            }
          } catch (error) {
            core.warning(`Could not inspect previous-head run ${runId} (${error.message}); continuing.`);
          }
        }
        // Enforcement point: runs of other PRs are never reusable, and every older ancestor
        // is further outside this PR. A PR's first run otherwise walked ten commits of main
        // (or of the branch it was cut from), fetching every run on each. An ancestor with no
        // runs at all is walked past: commits pushed together get no runs of their own.
        if (inspected > 0 && !ownRun) {
          core.info(`Ancestor ${firstParentSha.slice(0, 7)} has no run of PR #${pullRequestNumber}; its history ends here.`);
          break;
        }
      } catch (error) {
        core.warning(`Could not inspect checks on ${firstParentSha} (${error.message}); falling back.`);
        break;
      }
      ancestorSha = firstParentSha;
    }

    core.info("No fresh successful ancestor was proven; using the pull request base.");
    return fallback;
  } catch (error) {
    core.warning(`Could not inspect prior workflow runs (${error.message}); falling back to the pull request base.`);
    return fallback;
  }
}

module.exports = { resolveIncrementalPrBase };
