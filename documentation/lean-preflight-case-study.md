---
title: How Lean contributors can get useful feedback sooner
description: A measured case for retrying a known failing Lean module before the full Riemann Hypothesis proof build.
---

# How Lean contributors can get useful feedback sooner

A one-file cleanup in the Riemann Hypothesis formalization broke proofs in two other files. The original CI log reported a missing `BorelSpace` instance in the Cayley-chart proof. On a local checkout, a targeted Lake build reproduced the diagnostic in **16 seconds with the baseline cache already restored** (one run). The same target passed on the original base commit. A contributor with that failing module name could check a fix locally, without queueing for an entire proof build. [Original failed run](https://github.com/leanprover-community/riemann-hypothesis/actions/runs/45820942055) · [Historical replay data](assets/lean-preflight/replay.json)

## Measure the wait before tuning the build

On November 26, GitHub reported **1,728 queued PR build workflows** for the project. The 25 most recently queued Lake jobs, the only ones sampled, all had the fork-runner label. Five fork jobs that had started had waited **9.3–10.3 hours**. The newest completed PR workflow sample yielded no eligible completed fork job, so it cannot estimate fork p95 completion time. The numbers for the five running jobs measure waiting time only. [Queue snapshot and job IDs](assets/lean-preflight/queue.json)

The merge queue had a different bottleneck. Of 25 completed merge-group jobs, median time waiting for a runner was **1 second** and p95 was **2 seconds**. Median cache hydration was **110 seconds**, and median proof and axiom checking was **18 seconds**. The project separates the merge queue from fork runners. A prehydrated dependency image could shorten that hydration once a runner starts a job. We have not measured it on the project's runners, and it does not shorten the wait for a runner. [Runner design](https://github.com/leanprover-community/riemann-hypothesis/blob/main/CACHE.md#self-hosted-runners) · [Paired cache benchmark](riemann-lean-ci.md)

With CI-esta installed, collect the same groups from GitHub Actions:

```sh
ci-esta-lean queue --repo leanprover-community/riemann-hypothesis --per-event 25
```

## Use imports and previous failures to choose a first check

The Lean preflight uses Lean's own import parser on the base and head Git trees. It walks reverse imports to show which source files can be affected, including consumers of removed imports. It also reads `selective-deps` manifests for inputs a source file reads outside its imports. The plan explains each selection with a dependency chain and points unknown build inputs to a full `lake build`.

We compared the plan with recorded diagnostics from four historical failed builds, using the exact merge commits logged by GitHub. The graph reached all **10 diagnostic files**, including **three absent from the Git diff**. These four failures illustrate what reverse imports recover. They are a small retrospective sample. The one-file change that broke the Cayley-chart proof still reached **689 modules**, which illustrates the cost of eagerly building the entire affected set. [Replay data](assets/lean-preflight/replay.json)

For a PR with a known failure, start from the checkout you want to test and request a retry plan:

```sh
ci-esta-lean preflight origin/main HEAD --previous-failure \
  src/Lib/DiscreteSeries/Haar/CayleyChart.lean
```

If you have the failed Lake log, `retry` can find the modules for you. Save a local
build log or download a finished GitHub Actions job log, then run this from the checkout
where you want to test the fix:

```sh
ci-esta-lean retry lake.log
```

For the Cayley-chart example, GitHub CLI can download the original job log:

```sh
gh api repos/leanprover-community/riemann-hypothesis/actions/jobs/139912708645/logs > lake.log
ci-esta-lean retry lake.log
```

Run it in the Lake project directory, or pass that directory with `--repo`. The
command takes module names from Lake's own failure lines, so it also reports a bad
import or a compiler that was killed. For a log reduced to its `error:` lines it
reads `srcDir` from `lakefile.toml`; pass `--source-root` for a `lakefile.lean`
project that sets one. It prints a `lake build` line for matching tracked files
still present in the checkout, once per module and in log order, and names on
standard error any failure it could not match. If no modules match, review the original failure or run the usual
build. A targeted retry gives early feedback before the full build and axiom checks.

Run the reported `retry_command` first. In the replay it was `lake build +Lib.DiscreteSeries.Haar.CayleyChart`. Hydration is additional on a cold checkout. Keep the required full build, `sorry` scan, and axiom checks as the merge gate. A good first pilot would make the retry available to fork contributors and measure the time until it reports a failing module, alongside the regular gate.

## Confirm dry-lint candidates with elaborated statements

Dry-lint can rank related Lean declarations by source similarity. A signature check gives reviewers another way to examine those candidates. CI-esta's statement command compares elaborated types from trusted build artifacts. It normalizes binder and universe names and keeps binder visibility. [Dry-lint Lean support](https://github.com/gigaverse-app/dry-lint/pull/201)

```sh
ci-esta-lean statements Main New.Reduction.OneSidedBound
```

Scanning 801 modules with a compiled version found one exact match. The public theorem `LFunction_ne_zero_of_half_lt_re` already delegates to `New.grh` and provides the named theorem used by the challenge workflow. The scan, run once on a local machine, took **123 seconds** and peaked at about **22 GiB**. That result supports running the check on a small shortlist selected by dry-lint. Useful generalizations can have different elaborated statement types. [Scanner output](assets/lean-preflight/theorem-matches.json) · [Public theorem](https://github.com/leanprover-community/riemann-hypothesis/blob/c5451bd3ba92480e05c4218f5221bb2900c58706/src/Main.lean#L17)

### Check a proof refactor against the baseline

Build both revisions with the pinned Lean compiler. Keep the baseline module's
`.olean` before rebuilding the second revision, or build in separate checkouts.
Compare the compiled types by their fully qualified names.

```sh
ci-esta-lean compare /tmp/base-Main.olean .lake/build/lib/lean/Main.olean \
  riemannHypothesis riemannZeta_eq_zero_re LFunction_ne_zero_of_half_lt_re \
  LFunction_eq_zero_re LFunction_eq_zero_re_of_isPrimitive
```

Use trusted artifacts from both builds. The comparison ignores binder and universe
parameter names and preserves binder visibility and the elaborated type structure.
It exits unsuccessfully if a requested declaration is missing or its type changed.
Run the project's proof build and axiom checks alongside this review.

The two most immediate changes serve different people. A prepared cache gives runner operators back time on every matching job. A targeted retry gives proof authors a way to inspect the failure they are trying to fix. Together they shorten the path from a diagnostic to a checked patch.
