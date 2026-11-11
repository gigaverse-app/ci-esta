// Replay the lifecycle specification against the real HTTP collector and store.
// The imported model owns admission policy; this adapter makes its transitions
// executable by pytest-quint-connect without duplicating that policy in Python.
module merged_pr_contract {
  import merged_pr_evidence as M from "./merged_pr_evidence"

  // Each event selects a driver call; r identifies an immutable run/attempt slot.
  // Unused fields retain neutral values so every event has the same wire shape.
  type Event = { op: str, r: int, value: str }
  var event: Event
  var automaticMode: bool

  // Compare visible results, not internal collector decisions. Zero means no
  // staging. The fixture encodes source IDs as costs, so published identifies
  // which sources actually reached the timing store.
  var observed: { staged: int, published: Set[int] }

  action init = all {
    M::init,
    automaticMode' = false,
    event' = { op: "init", r: 0, value: "" },
    observed' = { staged: 0, published: Set() }
  }

  // Choose automatic discovery before any producer starts. It shares source
  // selection with explicit collection but requires workflow success at merge.
  action automatic = all {
    M::s.count == 0,
    M::s.lifecycle == "open",
    not(automaticMode),
    M::idle,
    automaticMode' = true,
    event' = { op: "automatic", r: 0, value: "" },
    observed' = observed
  }

  // Remote events alone cannot publish evidence. Observations change only when
  // the collector stages or publishes, or a worker crash discards staging.
  action push = all {
    M::push,
    automaticMode' = automaticMode,
    event' = { op: "push", r: 0, value: "" },
    observed' = observed
  }

  action start = all {
    M::start,
    automaticMode' = automaticMode,
    event' = { op: "start", r: 0, value: "" },
    observed' = observed
  }

  action passGate(r: int): bool = all {
    M::passGate(r),
    automaticMode' = automaticMode,
    event' = { op: "passGate", r: r, value: "" },
    observed' = observed
  }

  // Gate completion, workflow completion and artifact delivery are separate
  // events so histories can exercise reporting and upload races around merge.
  action finish(r: int, value: str): bool = all {
    M::finish(r, value),
    automaticMode' = automaticMode,
    event' = { op: "finish", r: r, value: value },
    observed' = observed
  }

  action upload(r: int, value: str): bool = all {
    M::upload(r, value),
    automaticMode' = automaticMode,
    event' = { op: "upload", r: r, value: value },
    observed' = observed
  }

  action expire(r: int): bool = all {
    M::expire(r),
    automaticMode' = automaticMode,
    event' = { op: "expire", r: r, value: "" },
    observed' = observed
  }

  action closePR = all {
    M::close,
    automaticMode' = automaticMode,
    event' = { op: "closePR", r: 0, value: "" },
    observed' = observed
  }

  // Seal the final head and latest admitted attempt, even if it is not green.
  // An older successful attempt must never become the fallback source.
  action merge = all {
    M::merge,
    automaticMode' = automaticMode,
    event' = { op: "merge", r: 0, value: "" },
    observed' = observed
  }

  // Probe the real collector even when evidence is ineligible or unavailable.
  // The model then idles and observations must remain unchanged; this catches
  // accidental admission of an open PR or an invalid artifact.
  action stage = {
    val ready = M::eligible and M::s.runs.get(M::s.sealed).artifact == "valid"
      and (not(automaticMode) or M::automaticEligible)
    all {
      if (ready) M::stage else M::idle,
      automaticMode' = automaticMode,
      event' = { op: "stage", r: 0, value: "" },
      observed' = if (ready)
        observed.with("staged", M::s.sealed)
      else
        observed
    }
  }

  // Publication consumes validated staging, which survives remote artifact
  // expiry. Set union expresses idempotency: retries cannot add a second copy.
  action publish = {
    val ready = M::eligible and M::s.staged == M::s.sealed
    all {
      if (ready) M::publish else M::idle,
      automaticMode' = automaticMode,
      event' = { op: "publish", r: 0, value: "" },
      observed' = if (ready)
        observed.with("published", observed.published.union(Set(M::s.sealed)))
      else
        observed
    }
  }

  // Lose local staging while preserving already published history.
  action crash = all {
    M::crash,
    automaticMode' = automaticMode,
    event' = { op: "crash", r: 0, value: "" },
    observed' = observed.with("staged", 0)
  }

  // Read back the result without mutating the model or implementation.
  action inspect = all {
    M::idle,
    automaticMode' = automaticMode,
    event' = { op: "inspect", r: 0, value: "" },
    observed' = observed
  }

  // Sample event orderings within the canonical model's three attempt slots.
  // Its guards exclude impossible remote events; stage/publish remain callable
  // before readiness to exercise refusal and later recovery.
  action step = {
    nondet r = 1.to(3).oneOf()
    nondet result = Set("success", "failure").oneOf()
    nondet artifact = Set("valid", "invalid").oneOf()
    any {
      automatic,
      push,
      start,
      passGate(r),
      finish(r, result),
      upload(r, artifact),
      expire(r),
      closePR,
      merge,
      stage,
      publish,
      crash,
      inspect
    }
  }

  // Reuse the canonical invariants. Replay separately compares the observed
  // staging and stored costs with the implementation after every event.
  val safety = M::safety

  // Late evidence must become usable after merge. Recover from a worker crash,
  // retain a validated copy after artifact expiry, and publish idempotently.
  run contractRecoveryTest = init
    .then(start)
    .then(passGate(1))
    .then(merge)
    .then(stage)
    .then(finish(1, "success"))
    .then(upload(1, "valid"))
    .then(stage)
    .then(crash)
    .then(stage)
    .then(expire(1))
    .then(publish)
    .then(publish)
    .then(all {
      assert(observed.published == Set(1)),
      inspect
    })

  // A green PR with a valid artifact cannot teach shared history while open.
  // Successful execution alone is insufficient admission.
  run contractOpenTest = init
    .then(start)
    .then(passGate(1))
    .then(finish(1, "success"))
    .then(upload(1, "valid"))
    .then(stage)
    .then(publish)
    .then(all {
      assert(observed.published == Set()),
      inspect
    })

  // A newer pending attempt supersedes the older green one at merge. Refusing
  // both catches implementations that search backward for any successful run.
  run contractLastTest = init
    .then(start)
    .then(passGate(1))
    .then(finish(1, "success"))
    .then(upload(1, "valid"))
    .then(start)
    .then(merge)
    .then(stage)
    .then(publish)
    .then(all {
      assert(observed.published == Set()),
      inspect
    })

  // Merge and green validation cannot make an invalid manifest trustworthy.
  // Refuse its costs instead of changing shared history.
  run contractInvalidTest = init
    .then(start)
    .then(passGate(1))
    .then(finish(1, "success"))
    .then(upload(1, "invalid"))
    .then(merge)
    .then(stage)
    .then(publish)
    .then(all {
      assert(observed.published == Set()),
      inspect
    })

  // No collector configuration is needed when the whole producer is green
  // before merge and pytest stamped the same execution identity into every XML.
  run contractAutomaticTest = init
    .then(automatic)
    .then(start)
    .then(passGate(1))
    .then(finish(1, "success"))
    .then(upload(1, "valid"))
    .then(merge)
    .then(stage)
    .then(publish)
    .then(all {
      assert(observed.published == Set(1)),
      inspect
    })

  // Automatic discovery must not guess required gates for a producer that
  // finishes after merge. The explicit collector handles that configured case.
  run contractAutomaticLateTest = init
    .then(automatic)
    .then(start)
    .then(passGate(1))
    .then(merge)
    .then(finish(1, "success"))
    .then(upload(1, "valid"))
    .then(stage)
    .then(publish)
    .then(all {
      assert(observed.published == Set()),
      inspect
    })

}
