// Composition of independently admitted merged PRs. Records here have already
// passed merged_pr_evidence; every immutable observation retains its source stamp.
module timing_publication {
  pure val WRITERS = Set(1, 2)
  pure val FILES = Set("shared", "a", "b")
  pure def observed(w: int): Set[str] = if (w == 1) Set("shared", "a") else Set("shared", "b")
  type State = { stored: Set[int], applied: Set[int], costs: str -> int }
  var s: State
  action init = s' = { stored: Set(), applied: Set(), costs: FILES.mapBy(_ => 0) }
  action upload(w: int): bool = s' = s.with("stored", s.stored.union(Set(w)))
  pure def newest(a: int, b: int): int = if (a > b) a else b
  // Stamps 1/2 order SOURCE observations, not merge/upload/download order.
  action reconcile(w: int): bool = all {
    s.stored.contains(w),
    s' = s.with("applied", s.applied.union(Set(w))).with("costs",
      FILES.mapBy(f => if (observed(w).contains(f)) newest(s.costs.get(f), w) else s.costs.get(f)))
  }
  action idle = s' = s
  action step = { nondet w = WRITERS.oneOf(); any { upload(w), reconcile(w), idle } }
  val noLostUpdates = FILES.forall(f => s.costs.get(f) ==
    s.applied.filter(w => observed(w).contains(f)).fold(0, (a, b) => newest(a, b)))
  val onlyStored = s.applied.subseteq(s.stored)
  val safety = noLostUpdates and onlyStored

  // Publisher mistakenly replaces the entire inventory / refreshes source stamps.
  action overwriteBug(w: int): bool = all {
    s.stored.contains(w),
    s' = s.with("applied", s.applied.union(Set(w))).with("costs",
      FILES.mapBy(f => if (observed(w).contains(f)) w else 0))
  }
  action brokenStep = { nondet w = WRITERS.oneOf(); any { step, overwriteBug(w) } }
  action check = all { assert(safety), idle }
  run reverseCompletionTest = init.then(upload(2)).then(upload(1))
    .then(reconcile(2)).then(reconcile(1)).then(check)
  run replayTest = init.then(upload(1)).then(reconcile(1)).then(upload(2))
    .then(reconcile(2)).then(reconcile(1)).then(check)
  run missingWriterTest = init.then(upload(1)).then(reconcile(1))
    .then(all { assert(s.costs.get("b") == 0), check })
}
