// Canonical lifecycle policy, replayed against the collector by contract.qnt.
// See docs/merged-pr-evidence.md for the implementation and adoption contract.
// One PR and one configured producer/environment; independent PRs compose through
// timing_publication.qnt. A slot represents an immutable (run_id, attempt).
module merged_pr_evidence {
  type Run = { head: int, gate: bool, result: str, artifact: str }
  type State = {
    lifecycle: str, head: int, count: int, runs: int -> Run,
    sealed: int, sealedHead: int, greenAtMerge: bool,
    staged: int, validated: Set[int], published: Set[int],
    reuseGranted: bool, matchingInputs: bool
  }
  pure val SLOTS = 1.to(3)
  pure val EMPTY = { head: 0, gate: false, result: "absent", artifact: "missing" }
  var s: State

  // Source ordering is admission/start ordering, never completion/webhook order.
  val latest = SLOTS.filter(r => s.runs.get(r).head == s.head)
    .fold(0, (a, b) => if (a > b) a else b)

  action init = s' = {
    lifecycle: "open", head: 1, count: 0, runs: SLOTS.mapBy(_ => EMPTY),
    sealed: 0, sealedHead: 0, greenAtMerge: false,
    staged: 0, validated: Set(), published: Set(),
    reuseGranted: false, matchingInputs: false
  }

  action push = all {
    s.lifecycle == "open", s.head < 2,
    s' = s.with("head", s.head + 1)
  }

  // Also permits explicit post-merge reruns: they cannot change the sealed source.
  action start = all {
    s.lifecycle != "closed", s.count < 3,
    s' = s.with("count", s.count + 1).with("runs",
      s.runs.set(s.count + 1, { head: s.head, gate: false, result: "pending", artifact: "missing" }))
  }

  action passGate(r: int): bool = all {
    s.runs.get(r).result == "pending",
    s' = s.with("runs", s.runs.set(r, s.runs.get(r).with("gate", true)))
  }

  // A whole workflow can fail in reporting after its required gate passed.
  action finish(r: int, result: str): bool = all {
    s.runs.get(r).result == "pending", Set("success", "failure").contains(result),
    s' = s.with("runs", s.runs.set(r, s.runs.get(r).with("result", result)))
  }

  // "valid" abstracts verified owner/head/attempt, environment and complete-file
  // manifest + exact shards. Untrusted, partial, wrong-key and malformed = invalid.
  action upload(r: int, artifact: str): bool = all {
    s.runs.get(r).head > 0, s.runs.get(r).artifact == "missing",
    Set("valid", "invalid").contains(artifact),
    s' = s.with("runs", s.runs.set(r, s.runs.get(r).with("artifact", artifact)))
  }

  action expire(r: int): bool = all {
    Set("valid", "invalid").contains(s.runs.get(r).artifact),
    s' = s.with("runs", s.runs.set(r, s.runs.get(r).with("artifact", "expired")))
  }

  action close = all {
    s.lifecycle == "open", s' = s.with("lifecycle", "closed")
  }

  // Model externally merged red/missing-check PRs too; they never become evidence.
  // Merge seals the final head and LAST producer attempt, not the last green one.
  action merge = all {
    s.lifecycle == "open",
    s' = s.with("lifecycle", "merged").with("sealed", latest)
      .with("sealedHead", s.head)
      .with("greenAtMerge", if (latest == 0) false else s.runs.get(latest).gate)
  }

  val eligible = s.lifecycle == "merged" and s.greenAtMerge and s.sealed > 0
    and s.runs.get(s.sealed).head == s.sealedHead
    and s.runs.get(s.sealed).result == "success"

  // Read/validate is separate from publication, exposing retry/crash/expiry races.
  action stage = all {
    eligible, s.runs.get(s.sealed).artifact == "valid",
    s' = s.with("staged", s.sealed).with("validated", s.validated.union(Set(s.sealed)))
  }

  action crash = s' = s.with("staged", 0)

  action publish = all {
    eligible, s.staged == s.sealed,
    // Immutable idempotency key: repository/PR/head/producer/attempt/environment.
    s' = s.with("published", s.published.union(Set(s.sealed)))
  }

  // Receipt admission remains separate from timing admission. "matchingInputs"
  // abstracts the existing exact receipt/context/freshness contract, not just SHA.
  action consume(matches: bool): bool = s' = s
    .with("matchingInputs", matches)
    .with("reuseGranted", matches and s.published.size() > 0)

  action idle = s' = s

  action step = {
    nondet r = SLOTS.oneOf()
    nondet result = Set("success", "failure").oneOf()
    nondet artifact = Set("valid", "invalid").oneOf()
    nondet matches = Set(true, false).oneOf()
    any { push, start, passGate(r), finish(r, result), upload(r, artifact),
      expire(r), close, merge, stage, crash, publish, consume(matches), idle }
  }

  val onlyMergedGreen = s.published.size() == 0 or (s.lifecycle == "merged" and s.greenAtMerge)
  val finalHeadOnly = s.published.forall(r => s.runs.get(r).head == s.sealedHead)
  val lastAttemptOnly = s.published.forall(r => r == s.sealed)
  val successfulValidatedOnly = s.published.forall(r =>
    s.runs.get(r).result == "success" and s.validated.contains(r))
  val atMostOnce = s.published.size() <= 1
  val timingsNeverGrantReuse = not(s.reuseGranted) or s.matchingInputs
  val safety = onlyMergedGreen and finalHeadOnly and lastAttemptOnly
    and successfulValidatedOnly and atMostOnce and timingsNeverGrantReuse

  // Liveness is conditional: source reports survive, reads recover, reconciliation
  // continues, and publication eventually wins a race with worker crashes.
  // No workflow can promise eventual learning if the only artifact is gone.
  action readyInit = s' = {
    lifecycle: "merged", head: 1, count: 1,
    runs: SLOTS.mapBy(r => if (r == 1)
      { head: 1, gate: true, result: "success", artifact: "valid" } else EMPTY),
    sealed: 1, sealedHead: 1, greenAtMerge: true,
    staged: 0, validated: Set(), published: Set(),
    reuseGranted: false, matchingInputs: false
  }
  action recoveryStep = any { stage, crash, publish, idle }
  temporal eventuallyPromoted = (weakFair(stage, s) and strongFair(publish, s))
    implies eventually(s.published.size() == 1)
  temporal noRetryGuarantee = eventually(s.published.size() == 1)

  // Deliberately broken alternatives: model checker must produce counterexamples.
  action publishOpenBug(r: int): bool = all {
    s.runs.get(r).result == "success", s.runs.get(r).artifact == "valid",
    s' = s.with("published", s.published.union(Set(r)))
  }
  action fallbackOlderGreenBug(r: int): bool = all {
    s.lifecycle == "merged", s.greenAtMerge, r < s.sealed,
    s.runs.get(r).head == s.sealedHead, s.runs.get(r).result == "success",
    s.runs.get(r).artifact == "valid",
    s' = s.with("published", s.published.union(Set(r)))
      .with("validated", s.validated.union(Set(r)))
  }
  action reuseTimingBug = all {
    s.published.size() > 0,
    s' = s.with("matchingInputs", false).with("reuseGranted", true)
  }
  action brokenOpenStep = { nondet r = SLOTS.oneOf(); any { step, publishOpenBug(r) } }
  action brokenFallbackStep = { nondet r = SLOTS.oneOf(); any { step, fallbackOlderGreenBug(r) } }
  action brokenReuseStep = any { step, reuseTimingBug }

  action check(condition: bool): bool = all { assert(condition), idle }
  action green(r: int): bool = passGate(r).then(finish(r, "success"))

  run normalTest = init.then(start).then(green(1)).then(upload(1, "valid"))
    .then(merge).then(stage).then(publish).then(check(s.published == Set(1) and safety))
  run neverMergedTest = init.then(start).then(green(1)).then(upload(1, "valid"))
    .then(stage).fail()
  run closedTest = init.then(start).then(green(1)).then(upload(1, "valid"))
    .then(close).then(stage).fail()
  run lateReportingTest = init.then(start).then(passGate(1)).then(merge)
    .then(check(not(eligible))).then(upload(1, "valid")).then(finish(1, "success"))
    .then(stage).then(publish).then(check(s.published == Set(1) and safety))
  run reportingFailureTest = init.then(start).then(passGate(1)).then(merge)
    .then(upload(1, "valid")).then(finish(1, "failure")).then(stage).fail()
  run newerPendingTest = init.then(start).then(green(1)).then(upload(1, "valid"))
    .then(start).then(merge).then(check(s.sealed == 2)).then(stage).fail()
  run newerFailedTest = init.then(start).then(green(1)).then(upload(1, "valid"))
    .then(start).then(passGate(2)).then(finish(2, "failure"))
    .then(merge).then(stage).fail()
  run oldHeadTest = init.then(start).then(green(1)).then(upload(1, "valid"))
    .then(push).then(merge).then(stage).fail()
  run invalidPayloadTest = init.then(start).then(green(1)).then(upload(1, "invalid"))
    .then(merge).then(stage).fail()
  run expiresBeforeFetchTest = init.then(start).then(green(1)).then(upload(1, "valid"))
    .then(merge).then(expire(1)).then(stage).fail()
  run durableStageTest = init.then(start).then(green(1)).then(upload(1, "valid"))
    .then(merge).then(stage).then(expire(1)).then(publish).then(check(safety))
  run crashRetryTest = init.then(start).then(green(1)).then(upload(1, "valid"))
    .then(merge).then(stage).then(crash).then(stage).then(publish)
    .then(publish).then(check(s.published == Set(1) and safety))
  run postMergeRerunTest = init.then(start).then(green(1)).then(upload(1, "valid"))
    .then(merge).then(start).then(green(2)).then(upload(2, "valid"))
    .then(stage).then(publish).then(check(s.sealed == 1 and s.published == Set(1) and safety))
  run receiptBoundaryTest = init.then(start).then(green(1)).then(upload(1, "valid"))
    .then(merge).then(stage).then(publish).then(consume(false))
    .then(check(not(s.reuseGranted))).then(consume(true)).then(check(s.reuseGranted and safety))
}
