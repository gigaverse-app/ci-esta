---
name: ci-esta
description: Measure and optimize GitHub Actions CI with CI-esta job/step reports, conservative evidence reuse and strict validation gates. Use for slow CI, repeated jobs, broad triggers or requests to prove CI savings; works with Python and non-Python application code.
license: Apache-2.0
---

# Find the work worth avoiding

Work in the user's target repository. CI-esta's hosted reporting and evidence
actions target GitHub Actions, regardless of the application's language. If the
target uses another CI provider, report that boundary and use its native timing
data; do not migrate providers merely to apply this skill. Python pytest suites
can use [pytest-selective](https://github.com/gigaverse-app/pytest-selective) with
other runners as well.

## Observe first

Inspect workflows, exact required job names, reusable workflows, current caches
and a recent completed run. Separate slow test execution, installs/services,
admission waits and overlapping superseded runs. Use the
[reporting recipe](references/adoption.md) for read-only CLI collection or a
completed-run observer. Pin a reviewed revision and report the source run's ID,
attempt and head, not the observer's own identity.

Keep reporting outside the validation dependency chain. The observer still uses
runner time; moving it does not make that cost disappear. Do not configure sticky
comments, publication or external telemetry unless the task authorizes them.
Use ordinary read credentials in environment/process memory, never in arguments
or committed reports.

## Choose one optimization supported by the data

- For Python dependency-based test or lane selection, use the pytest-selective
  skill. CI-esta consumes its explanations; it does not implement another graph.
- For broad workflow triggers in any language, map job inputs and preserve
  always-running docs/package checks. Add real change-based routing controls,
  including relevant code/lock/workflow changes and unknown-input fallbacks.
- For redundant PR revisions, check existing concurrency before adding it.
  Scope supersession to the same PR/workflow; preserve deliberate full runs.
- For installation/setup bottlenecks, verify cache keys cover locks, interpreter
  and platform. Measure a warm and cold path before claiming general savings.
- Reuse completed lanes only when repeating the same declared work is the actual
  bottleneck. A prior green workflow is not sufficient proof.

## Evidence reuse is optional

Read the [evidence-reuse guide](https://github.com/gigaverse-app/ci-esta/blob/main/docs/evidence-reuse.md)
before adding it. Begin with whole-tree identity. Narrow `input-paths` only after
reviewing source, tests, setup/workflows, locks and pinned external inputs; those
paths are literal files/directories, not pytest-selective glob patterns.

Emit a completion receipt only after every required test and evidence validator
passes. Keep the planner required, execute on uncertain proof, and use a strict
aggregate gate with a boolean map matching its direct prerequisites. Missing,
failed, cancelled or unexpectedly skipped work must not turn green. Preserve
explicit reruns and scheduled/full validation. External services and changing
state need their own policy; do not infer conformance from an unchanged Git tree.

Verify eligible reuse plus changed-input, missing-proof and explicit-rerun
execution controls. If that evidence cannot be collected within the task, ship
useful reporting/routing improvements and leave reuse disabled with the reason.

## Deliver measured work

Follow the task's existing PR/merge scope. Provide the changed config, regression
evidence and a concise table of elapsed time, summed runner-seconds, job counts,
run/attempt/head identities and preserved checks. For a causal selection claim,
compare a successful selected run and full control on the same checked-out
revision. Separate reporter overhead and cancelled attempts from the comparison;
retain them when discussing total iteration cost. Rounded minutes/dollars are
estimates, not billing records.

If API access is unavailable, prepare the local changes and exact collection
command, explicitly marking live impact unmeasured. Do not substitute test-count
reductions for measured time. The published
[92.3% README routing result](https://github.com/gigaverse-app/ci-esta/blob/main/docs/benchmarks/2026-10-22.md)
comes from pytest-selective and consumer input declarations, not receipt reuse.
