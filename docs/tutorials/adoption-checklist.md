---
title: Adopt CI-esta, one measured improvement at a time
description: A staged tutorial and completion checklist covering reporting, selection, setup, timing retention, execution, evidence reuse, diagnostics and specialist tools.
---

# Adopt CI-esta, one measured improvement at a time

Start with one workflow and its required gate. Measure it, choose the most useful
change, and keep that change only after checking its result. You do not need to
enable every action. Mark a capability **adopted**, **not applicable**, or
**deferred with a reason**; an unchecked catalog is not an adoption plan.

This tutorial gives the order, acceptance checks and rollback choices. Linked
recipes own the complete configurations. Use the
[pytest-selective checklist](https://github.com/gigaverse-app/pytest-selective/blob/main/docs/tutorials/adoption-checklist.md)
for dependency declarations, local development and selection health.

## 1. Record a useful baseline

First inspect what the repository already wires:

```bash
uvx --from ci-esta ci-esta adoption --root .
uvx --from ci-esta ci-esta adoption --root . --json > adoption.json
```

These commands use a separate tool environment; no application dependency is
needed. The command follows local composite actions and reusable workflows. It suggests
reporting, selection, shared checkpoint defaults and timing-feedback gaps with
source paths. It never modifies files, enables retention or fails CI for optional
advice. `--ignore SUGGESTION_ID` suppresses advice you have reviewed without
hiding the detected action inventory. Remote workflows and arbitrary scripts
remain explicit inspection limits. A configured action is not evidence of a
successful run, compatible timing lanes or measured savings.

Install CI-esta in a separate tool environment, or use its hosted reporting
action. Actions do not require adding CI-esta to your application's dependencies.
For local reporting, set an authorized read token in `GH_TOKEN` or `GITHUB_TOKEN`.
Replace the uppercase values and exact gate name below:

```bash
ci-esta report --repository OWNER/REPO --run-id RUN_ID --run-attempt 1 \
  --commit-sha SOURCE_HEAD_SHA --gate 'Validation gate' --critical-path \
  --output-dir ci-esta-report
ci-esta render ci-esta-report/ci-observability.json \
  --markdown report.md --prometheus report.prom
```

- [ ] List the exact required checks, test commands, services and coverage contracts.
- [ ] Confirm the report's source run, attempt, checkout identity and gate selectors.
- [ ] Record gate elapsed time, summed runner-seconds, slowest steps and cancelled work.
- [ ] Inspect missing topology, collection errors and unavailable rates before interpreting estimates.
- [ ] Add the [completed-run observer](../quickstart.md#report-a-completed-workflow)
  outside the required validation dependency chain. Keep it summary-only unless
  PR comments are wanted; measure observer overhead separately.

**Done when:** you can name the blocking cost and show the source evidence.
If reporting is the only useful change, stopping here is a valid adoption.

## 2. Skip unaffected work before provisioning it

Use [whole-lane selection](https://github.com/gigaverse-app/pytest-selective/blob/main/docs/ci.md#select-whole-ci-lanes)
when a suite must retain complete coverage or conformance evidence. Use file
selection for ordinary suites that support partial collection. Keep unrelated
type checking, CI lint and security admission independently selectable.

- [ ] Declare source, tests, locks, collection policy, runtime reads, execution
  workflows, called actions, generated inputs and external pins.
- [ ] Fetch enough Git history; choose a base covering the complete change set.
- [ ] Prove that unreferenced docs run zero tests, while source, fixture, lock and
  execution-workflow changes retain the appropriate work.
- [ ] Exercise missing history, invalid configuration and an explicit full override.
- [ ] Keep the planner required. A successful empty plan skips pytest; a failed
  planner must not create a green empty route.
- [ ] Keep full scheduled/manual checkpoints and existing conformance validators.

The selector's `full: auto` default supplies checkpoints for reruns, manual,
scheduled and release events, and `test:full`; ordinary PRs and pushes remain
selective. `base` defaults to the PR base or push's previous commit. Keep an
explicit base for validated incremental evidence and an explicit `full` override
for coverage or manual experiments. Consume `test_roots_json` for file plans so
paths survive job boundaries without shell splitting. Verify your selected
action revision supports these defaults before deleting older expressions.

Follow [selected gates](../selected-gates.md), then validate the finished wiring:

```bash
ci-esta check-workflow --workflow .github/workflows/ci.yml \
  --lanes .github/test-lanes.json
```

**Done when:** real Git-change controls exercise both admission and the required
gate. **Rollback:** force full selection while repairing declarations; do not
consume an old plan after a failed command.

## 3. Remove repeated setup that the measurements identify

Follow [environment caching](../environment-cache.md). Start with uv's download
cache and locked synchronization. Compare a complete environment restore only
if installation still dominates.

- [ ] Match Python and uv versions to the project's actual toolchain requirements.
- [ ] Include all groups/extras, workspace manifests, platform and ABI variants in identity.
- [ ] Verify cold setup, a warm restore, a changed lock and an unusable cached interpreter.
- [ ] Confirm locked synchronization still runs after restore.
- [ ] Measure restore and save time as well as installation time.
- [ ] Use `cache-environment: false` if archive overhead loses to reconstruction.

**Done when:** a successful equivalent workload saves useful time, with the same
installed environment. A cache hit alone is not evidence of improvement.

## 4. Close the timing and execution loop

Begin with the existing pytest/xdist arrangement. Use the
[executable timing tutorial](../learned-test-timings.md#cli-and-runnable-tutorial)
before wiring retained history or adding runner jobs:

```bash
# In a CI-esta checkout with uv sync --locked completed:
uv run python examples/timing-history/run.py
```

Then adapt the [complete sharding workflow](../../examples/pytest-shards/workflow.yml).

- [ ] Choose one timing key per OS, Python version, service and fixed marker lane.
- [ ] Opt in with `history-key`; keep replacement behavior if retention is unnecessary.
- [ ] Validate every expected shard before declaring `complete-files: 'true'`.
  Whole-file partial runs are supported; ad hoc case filtering cannot replace a file's cost.
- [ ] Restore once before planning. Pass the exact plan or frozen duration input
  to all workers, including workers on different runners.
- [ ] Keep unknown-file fallback and current inventory authoritative.
- [ ] Isolate databases, queues, ports and temporary paths before adding concurrency.
- [ ] Verify every selected file occurs exactly once, including the final short pool.
- [ ] Preserve failing, interrupted and unexpectedly empty shard outcomes.
- [ ] Verify partial updates, stale reports, old-workflow reruns and concurrent
  writers using the [local and hosted examples](../learned-test-timings.md).
- [ ] Compare runner startup, slowest shard and total runner-seconds across candidate pool sizes.

**Done when:** the complete workload still passes and measured scheduling improves.
**Rollback:** remove the history key and restore step, or choose a new key to reset.
Use `history-publish: 'false'` for a read/compute-only rollout; adjust download
budget, artifact lifetime, trusted branch or strict restoration only as needed.
The 14-day removed-file grace is separate from artifact retention.

## 5. Reuse completed work only after admission is trustworthy

Use [receipt-based reuse](../evidence-reuse.md) when repeating an already
validated job is a measured cost. Start with whole-tree identity. Different
runtime choices need different `execution-context` values.

- [ ] Place the receipt after every required test and evidence validator.
- [ ] Demonstrate reuse of a matching successful lane.
- [ ] Demonstrate execution after changed inputs, missing/stale proof, a newer
  contradictory failure, a fork, and an explicit full/rerun request.
- [ ] Keep planner failure and unexpectedly skipped prerequisites fatal to the gate.
- [ ] Keep scheduled full runs for changing external state that Git cannot describe.

**Done when:** both reuse and negative execution controls run through the real
workflow. **Rollback:** remove the reuse admission and execute the lane normally.
Timing manifests, duration estimates and selection plans are never completion receipts.

## 6. Select remaining capabilities by the problem they solve

Every current public action is mapped below. Names link through the
[complete action reference](../actions.md); read the selected action's inputs
before copying it. Most rows are alternatives or specialist additions, not
mandatory installation steps.

| Problem / acceptance check | Actions | Recipe |
| --- | --- | --- |
| Understand time and critical paths; confirm source identities | `ci-observability`, `ci-observability-enrichment` | [Reports](../github-actions-observability.md), [measured impact](../measured-impact.md) |
| Export metrics or shard intervals; confirm destination and source identity | `publish-prometheus-snapshot`, `publish-shard-measurements` | [Runner diagnostics](../runners-and-diagnostics.md), [report integration](../integrations.md) |
| Collect complete changes once; test renames, deletions and incomplete history | `collect-pr-changes`, `collect-pytest-changes`, `collect-ci-changes` | [Selection and gates](../selected-gates.md) |
| Reject stale reruns and superseded work; preserve deliberate full runs | `current-pr-head`, `cancel-obsolete-pr-runs` | [Critical-path optimizations](../critical-path-optimizations.md) |
| Choose test/type-check scope; validate changed-input and full fallbacks | `test-impact`, `typecheck-scope`, `pytest-expansion` | [Selector checklist](https://github.com/gigaverse-app/pytest-selective/blob/main/docs/tutorials/adoption-checklist.md) |
| Install efficiently; validate exact identity and broken-cache repair | `setup-cached-uv`, `setup-python-uv`, `native-windows-git` | [Environment cache](../environment-cache.md), [platform tuning](../critical-path-optimizations.md) |
| Retain costs and partition current tests; verify partial/stale/concurrent updates | `restore-test-timings`, `learn-test-timings`, `plan-pytest-shards`, `plan-runner-pools` | [Timing tutorial](../learned-test-timings.md) |
| Aggregate exact artifacts and retain coverage policy; fail on missing shards | `pytest-timings`, `verify-pytest-completion`, `coverage-policy` | [Sharding example](../../examples/pytest-shards/workflow.yml), [runner guide](../runners-and-diagnostics.md) |
| Replay previously failing whole files; retain unresolved failures | `pytest-failure-canary`, `pytest-canary-pr-state` | [Action contracts](../actions.md), [Python tuning](../python-ci-tuning.md) |
| Reuse successful evidence or a proven scan base; verify negative controls | `resolve-lane-evidence`, `resolve-pytest-evidence`, `resolve-incremental-pr-base`, `validation-gate` | [Reuse policy](../evidence-reuse.md) |
| Admit and run security checks without weakening their failure policy | `resolve-security-trigger`, `semgrep-scan`, `semgrep-scan-ci-code`, `trivy-scan-ci-code`, `trivy-scan-image` | [Non-Python and security integrations](../non-python.md), [action contracts](../actions.md) |
| Validate workflow/action/shell changes; prove invalid inputs fail | `lint-ci-code` | [Workflow and source rules](../runners-and-diagnostics.md#source-tree-and-workflow-rules) |
| Use PostgreSQL tools matching the service; verify isolated test DB behavior | `postgres-client` | [PostgreSQL setup](../postgres-client.md) |
| Reuse a matching immutable image; test changed-build-input misses | `reuse-ecr-image` | [Image action contract](../../actions/reuse-ecr-image/action.yml) |
| Select actual Bun tests or report an existing runner; preserve repository discovery | `run-bun-tests`, `report-bun-tests` | [Bun tutorial](../bun-test-selection.md) |

For each adopted row, record the workflow/job, input assumptions, exercised
success and failure controls, measured result, opt-out and maintainer. Mark
unneeded rows explicitly so future maintainers know they were considered.

## 7. Use supported commands instead of copying helper scripts

| Surface | Purpose and adoption boundary |
| --- | --- |
| `ci-esta adoption`, `report`, `render`, `check-workflow` | Read-only adoption inventory, reporting, offline rendering and gate-wiring checks; use the commands above. |
| `ci-esta-pytest learn`, `history`, `plan`, `pools`, `run-local` | The timing-to-execution loop; use the [timing](../learned-test-timings.md) and [pool](../runners-and-diagnostics.md) recipes. |
| `ci-esta-pytest merge`, `junit`, `coverage` | Existing duration-manifest aggregation, JUnit summaries and coverage validation. `merge` is not chronological history retention. |
| `ci-esta-pytest canary`, `canary-run` | Plan and execute bounded previous-failure files; inspect `--help` and preserve the full selected inventory. |
| `ci-esta-resources`; `ci_esta.testing.pytest_watchdog` | Opt-in Linux resource reports and pytest progress/thread diagnostics; verify original exit status and cleanup. See [diagnostics](../runners-and-diagnostics.md#resource-and-pytest-diagnostics). |
| `ci-esta-postgres-clone` | Clone disposable test databases for isolated workers. Requires the `postgres` extra; replaces worker databases. Follow the [database recipe](../critical-path-optimizations.md#parallel-django-tests-without-repeating-migrations). |
| `ci-esta-enrich` | Adapt supported consumer evidence into the shared report; inspect its subcommands and [integrations](../integrations.md). Repository-specific adapters are not universal discovery. |
| `ci-esta-image` | Specialist image digest, sanitization, disposable pull and node-observation probes. Inspect `--help`; Docker/Kubernetes access and explicit disposable targets are caller-owned. These are not baseline adoption commands. |
| `ci-esta-drill` | Live mutation/PR drills for the built-in Gigaverse consumer profiles. It creates or changes remote test resources; do not run it as a generic read-only audit. See the [implementation contract](../../src/ci_esta/drill.py). |
| `examples/timing-history/run.py`, `examples/pytest-shards/run_shard.py` | Executable learning example and a small exact-file runner to adapt to your isolation requirements. |
| `scripts/ci/environment_cache.py`, `coverage-policy.cjs`, `record_measurement.py` | Implementation helpers owned by setup, coverage and measurement actions. Invoke the owning action instead of vendoring these files. |
| `scripts/ci/github_script_surface.py`, `pytest_selective_requirement.py` | Internal CI extraction/dependency helpers; no separate adopter installation. |
| `scripts/render_brand.py`, `render_sticky_banners.py`; `documentation/*.py` | Toolkit artwork, documentation publishing and validation tooling; maintainers use them, consumer CI does not need them. |

Use [import-linter and the additional filesystem guards](../runners-and-diagnostics.md#source-tree-and-workflow-rules)
for architectural contracts when relevant. Treat test inventory, dependency
graphs and partitioning as pytest-selective's contracts rather than implementing
another selector in a consumer script.

For new projects, prefer `setup-cached-uv` with explicit groups. The simpler
`setup-python-uv` installs **all** dependency groups; use it only when that is
your intended development environment. `github_script_surface.py` is a
compatibility entry point for the Octokit contract recorder, not a required
consumer script.

## 8. Prove the benefit and hand it over

- [ ] Run successful selected/full controls on the same head and tested checkout;
  preserve test arguments, environment and required gate names.
- [ ] Compare cold/warm cache conditions separately. Include planning, services,
  artifacts, reporting and cancelled attempts in the appropriate cost totals.
- [ ] Record elapsed seconds, summed runner-seconds and repeated samples before
  claiming a stable improvement. File-count reduction is not a time saving.
- [ ] Link the raw runs, exact tool revisions, preserved correctness checks and
  rollback in the adoption PR. Use the [measurement recipe](../measured-impact.md).
- [ ] Verify the no-change, documentation-only, source, shared fixture, dependency,
  workflow, missing-history and explicit-full routes after integration.
- [ ] Update the [portable skill](../../skills/ci-esta/SKILL.md) installed by your team
  separately from Actions and Python dependencies.

Moving `@v1` actions receive compatible published action updates. Immutable pins
and installed packages need explicit updates; local skills need refreshes too.
Installing a newer release does not enable optional retention, reuse, comments,
external metrics or new workflow jobs. Keep those choices visible in configuration.
