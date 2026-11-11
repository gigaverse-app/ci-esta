// Replay the lifecycle specification against the real HTTP collector and store.
// Remote events are inputs; only staged source and published costs are observed.
module merged_pr_contract {
  import merged_pr_evidence as M from "../../specs/merged_pr_evidence"
  type Event = { op: str, r: int, value: str }
  var event: Event
  var observed: { staged: int, published: Set[int] }
  action init = all { M::init, event' = {op: "init", r: 0, value: ""},
    observed' = {staged: 0, published: Set()} }
  action push = all { M::push, event' = {op: "push", r: 0, value: ""}, observed' = observed }
  action start = all { M::start, event' = {op: "start", r: 0, value: ""}, observed' = observed }
  action passGate(r: int): bool = all { M::passGate(r),
    event' = {op: "passGate", r: r, value: ""}, observed' = observed }
  action finish(r: int, value: str): bool = all { M::finish(r, value),
    event' = {op: "finish", r: r, value: value}, observed' = observed }
  action upload(r: int, value: str): bool = all { M::upload(r, value),
    event' = {op: "upload", r: r, value: value}, observed' = observed }
  action expire(r: int): bool = all { M::expire(r),
    event' = {op: "expire", r: r, value: ""}, observed' = observed }
  action closePR = all { M::close, event' = {op: "closePR", r: 0, value: ""}, observed' = observed }
  action merge = all { M::merge, event' = {op: "merge", r: 0, value: ""}, observed' = observed }
  action stage = {
    val ready = M::eligible and M::s.runs.get(M::s.sealed).artifact == "valid"
    all {
      if (ready) M::stage else M::idle,
      event' = {op: "stage", r: 0, value: ""},
      observed' = if (ready) observed.with("staged", M::s.sealed) else observed
    }
  }
  action publish = {
    val ready = M::eligible and M::s.staged == M::s.sealed
    all {
      if (ready) M::publish else M::idle,
      event' = {op: "publish", r: 0, value: ""},
      observed' = if (ready) observed.with("published", observed.published.union(Set(M::s.sealed))) else observed
    }
  }
  action crash = all { M::crash, event' = {op: "crash", r: 0, value: ""},
    observed' = observed.with("staged", 0) }
  action inspect = all { M::idle, event' = {op: "inspect", r: 0, value: ""}, observed' = observed }
  action step = {
    nondet r = 1.to(3).oneOf()
    nondet result = Set("success", "failure").oneOf()
    nondet artifact = Set("valid", "invalid").oneOf()
    any { push, start, passGate(r), finish(r, result), upload(r, artifact), expire(r),
      closePR, merge, stage, publish, crash, inspect }
  }
  val safety = M::safety
  run contractRecoveryTest = init.then(start).then(passGate(1)).then(merge).then(stage)
    .then(finish(1, "success")).then(upload(1, "valid")).then(stage).then(crash)
    .then(stage).then(expire(1)).then(publish).then(publish)
    .then(all { assert(observed.published == Set(1)), inspect })
  run contractOpenTest = init.then(start).then(passGate(1)).then(finish(1, "success"))
    .then(upload(1, "valid")).then(stage).then(publish)
    .then(all { assert(observed.published == Set()), inspect })
  run contractLastTest = init.then(start).then(passGate(1)).then(finish(1, "success"))
    .then(upload(1, "valid")).then(start).then(merge).then(stage).then(publish)
    .then(all { assert(observed.published == Set()), inspect })
  run contractInvalidTest = init.then(start).then(passGate(1)).then(finish(1, "success"))
    .then(upload(1, "invalid")).then(merge).then(stage).then(publish)
    .then(all { assert(observed.published == Set()), inspect })
}
