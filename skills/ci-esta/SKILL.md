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

## Public onboarding

Use the [quickstart](https://github.com/gigaverse-app/ci-esta/blob/main/docs/quickstart.md)
and [public action API](https://github.com/gigaverse-app/ci-esta/blob/main/docs/actions.md).
Prefer `gigaverse-app/ci-esta@REF` for reporting and `/setup-cached-uv@REF` or
other named public actions under `gigaverse-app/ci-esta/actions/NAME@REF`
for setup/execution. Check that the selected release
contains the entry point. Retain old paths for existing pinned consumers until
upgrading; never present an unreleased path as available at an old tag.
Actions install their own support tools. Add the Python package to the test
environment only when invoking its CLI or pytest plugins.

## Observe first

Inspect workflows, exact required job names, reusable workflows, current caches
and a recent completed run. Separate slow test execution, installs/services,
admission waits and overlapping superseded runs. Use the
[reporting recipe](references/adoption.md) for read-only CLI collection or a
completed-run observer. Use a compatible release tag and report the source run's ID,
attempt and head, not the observer's own identity.

Use `ci-esta report --critical-path` and the named aggregate gate to compute the
observed chain and execution-only CPM/slack from the source workflow at its
commit. Read [critical-path analysis](https://github.com/gigaverse-app/ci-esta/blob/main/docs/critical-path.md).
A Gantt or longest job alone is not a dependency critical path. Report unknown
topology explicitly; delay includes scheduling and startup, not only runner queue.

Keep reporting outside the validation dependency chain. The observer still uses
runner time; moving it does not make that cost disappear. Do not configure sticky
comments, publication or external telemetry unless the task authorizes them.
Use ordinary read credentials in environment/process memory, never in arguments
or committed reports.

## Choose one optimization supported by the data

- For Python dependency-based test or lane selection, use the pytest-selective
  skill. CI-esta consumes its explanations; it does not implement another graph.
- For a repository whose actual test command uses Bun, use the
  [Bun adapter](https://github.com/gigaverse-app/ci-esta/blob/main/docs/bun-test-selection.md) and native `--changed=<base>`.
  TypeScript does not imply Bun: inspect the runner first. Keep repository
  discovery authoritative, declare always-run contracts and non-import inputs,
  retain isolation/batching and full checkpoints, and compare actual inventories
  and elapsed times on the same revision. Do not install pytest-selective into
  a JavaScript project or copy a consumer's import graph/allowlist into CI-esta.
- For broad workflow triggers in any language, map job inputs and preserve
  always-running docs/package checks. Add real change-based routing controls,
  including relevant code/lock/workflow changes and unknown-input fallbacks.
- For redundant PR revisions, check existing concurrency before adding it.
  Scope supersession to the same PR/workflow; preserve deliberate full runs.
- For installation/setup bottlenecks, verify cache keys cover locks, interpreter
  and platform. Measure a warm and cold path before claiming general savings.
- Use the shared `setup-cached-uv` action for exact environment identity, broken
  restore repair and mandatory locked synchronization. Keep cache variants for
  application ABI/system dependencies; never use a cache hit as test evidence.
- Choose runner capacity and local process count separately. Benchmark one larger
  runner, several standard runners or several larger pools against the existing
  layout. Use the [complete shard recipe](https://github.com/gigaverse-app/ci-esta/tree/main/examples/pytest-shards)
  and preserve every shard's completion checks. Do not turn 16 local workers into
  16 hosted jobs accidentally. Larger runners have a different billing policy.
- Learn file costs from successful JUnit with `ci-esta-pytest learn`; retain
  separate lane/matrix artifacts. Follow the
  [timing feedback tutorial](https://github.com/gigaverse-app/ci-esta/blob/main/docs/learned-test-timings.md).
  Benchmark whole-file pools against existing xdist before adding runners.
  Preserve service isolation, coverage and domain conformance checks.
- Reuse completed lanes only when repeating the same declared work is the actual
  bottleneck. A prior green workflow is not sufficient proof. A passing lane from
  a partly failed workflow may be reusable when its own receipt and freshness
  checks pass.

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

Use the [measured-impact recipe](https://github.com/gigaverse-app/ci-esta/blob/main/docs/measured-impact.md)
when publishing savings or tuning caches. Lead the sticky with what ran, what was
avoided and verified before/after evidence; keep Gantt/critical-path diagnostics
collapsed. Separate historical benchmarks from the current run. For Bun, retain
structured inventory, wall time, fallback and runtime evidence; never translate
file-count reduction into measured time savings.

Measure cache-key evaluation and save/restore overhead. Compute recursive input
hashes once before installing dependencies, verify the actual installed-tool
directory, and still execute locked synchronization/compiler checks. Audit broad
label triggers while preserving intentional label-driven workflows and explicit
full reruns. Check the exact branch-required job also fails when planning fails.

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
