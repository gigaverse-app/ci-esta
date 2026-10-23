# Affected tests with Bun

Use this adapter when the repository actually runs `bun test`. TypeScript and
React identify source languages and libraries, not the test runner. A project
using Bun only to install packages may still run Jest, Vitest or Playwright.
Keep those runners and their native selection contracts. Python pytest projects
continue to use pytest-selective; CI-esta does not build a second import graph.

## Contract and ownership

The public action is `gigaverse-app/ci-esta/run-bun-tests`; see
[entry-point availability](actions.md) before selecting a release pin.
Pin a reviewed commit. It needs Node 22+ and Bun >=1.4.2 <2 installed by the caller;
it installs no Python or application dependencies. Bun owns static/transitive
imports, aliases and literal dynamic imports through
[`--changed=<base>`](https://bun.sh/blog/bun-v1.4). The adapter owns conservative
admission, exact repository inventory, full fallback, execution and reporting.

The repository owns discovery, global inputs, preload/setup, coverage policy,
explicit full checkpoints, required check names and always-run contracts.
The JSON boundary avoids importing arbitrary consumer code into the planner or
hardcoding a monorepo layout in CI-esta. It also works without GitHub Actions:
import `planAffectedTests`, `readTestSelection` from `selection.mjs` or
`runBunTests` from `run.mjs` in a pinned checkout of the action directory.
No npm package or generic plugin registry is needed for this single native adapter.
The action also exposes `selection-module`, an absolute module path in the current
job, so consumer controls can exercise their real policy against the pinned planner.

1. Produce a complete inventory with the repository's existing discovery code:

```json
{
  "schema_version": "ci-esta/bun-inventory/v1",
  "files": ["src/value.test.ts", "scripts/structure.test.mjs"],
  "alwaysRunFiles": ["scripts/structure.test.mjs"]
}
```

Every path is a literal repository-relative test file. Duplicates, invalid paths,
missing files, an empty inventory or an always-run file outside the inventory
fail validation. There is no safe full fallback when the complete suite is unknown.
Maintain an independent consumer test proving discovery covers all existing lanes.
The `alwaysRunFiles` subset executes even when no application tests are affected.
Use it for repository structure, source-scanning and filesystem contracts that an
import graph cannot represent. Their helpers remain explicit policy inputs.

2. Commit a repository-owned policy:

```json
{
  "schema_version": "ci-esta/bun-policy/v1",
  "scopedRoots": ["src/features/"],
  "runtimeRoots": ["src/"],
  "sourceExtensions": [".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".mts", ".cts"],
  "unaffectedPaths": ["README.md"],
  "unaffectedRoots": ["docs/"],
  "reviewedReaders": {}
}
```

Roots end in `/`. Only Markdown under `unaffectedRoots` is unaffected; a script
under docs is not documentation. Inputs outside the declared source/docs scope
run the full inventory. Include every runtime/helper root used by scoped tests
in `runtimeRoots`; application-specific globals stay outside `scopedRoots`.
Locks, packages, patches, preload, tsconfig, assets and CI files should normally
remain global full-suite inputs. Narrow the scope only with consumer evidence.

The adapter detects common opaque reads (`Bun.file`, `fs`, `readFile`, computed
imports and `import.meta.glob`). A reader outside always-run files forces full
execution unless `reviewedReaders[path]` declares its exact Git `blob` and a list
of literal `inputs` (trailing `/` means a directory). Changes to those inputs
run the full suite. Review the code before recording `git hash-object <reader>`;
never automatically refresh fingerprints just to regain selection. Even comment
matches require review. This conservative lexical check is a guard, not proof
that every possible runtime dependency has been discovered. External service
state, runtime-generated imports and environment-dependent selection require a
full/conformance policy of their own.

3. Invoke after dependency installation and inventory generation:

```yaml
- run: bun run test --inventory > "$RUNNER_TEMP/bun-inventory.json"
- uses: gigaverse-app/ci-esta/actions/run-bun-tests@main
  with:
    inventory: ${{ runner.temp }}/bun-inventory.json
    policy: .github/test-selection.json
    base: ${{ github.event.before }}
    full: ${{ github.run_attempt > 1 || github.event_name == 'schedule' }}
    shards: '8'
    args: '["--isolate","--parallel"]'
    output-directory: ${{ runner.temp }}/bun-test-selection
```

The inventory command is an adopter API, not a built-in Bun flag. For a PR use
its trusted base SHA; for a push use `event.before`; manual measurements supply
an explicit base SHA. Fetch history. Preserve main/scheduled full checkpoints,
explicit full overrides and reruns. Do not apply a whole-suite coverage floor
to a subset or lower a floor to make it pass. Coverage lanes should stay full.

`shards` means sequential fresh-process batches on one runner, not a matrix.
The adapter partitions the complete sorted inventory once. On a full run each
batch runs unchanged; on a scoped run each batch separates always-run contracts
from candidates passed to Bun. Both preserve the supplied isolation/parallelism
flags. Empty groups never invoke Bun. All batches finish and any failed batch
keeps the final exit code nonzero. Supported flags are isolation, parallelism,
timeout, concurrency, seed, randomization and dots; selection/output flags are
owned by the adapter. There is no retry of a failed selected test as a full run
that could conceal its failure.

Missing/invalid history, dirty tracked files, untracked inputs, malformed policy,
unknown paths, symlinks, renames/deletions and changed reader fingerprints execute
the full inventory. Optional persisted plans are recomputed at execution; stale,
missing or forged reuse plans fall back to full. An explicit full override wins.
Keep generated inventory/reports outside the worktree (for example RUNNER_TEMP).
Unsupported runtime versions and missing inventory fail visibly.

## Evidence and reports

The sticky now includes structured executed/full file counts, test wall time,
runtime, mode/result, and a collapsed inventory. See
[measured impact](measured-impact.md) to add verified full/selected benchmark pairs
without mistaking file-count reduction for a measured time saving.

Upload `execution-selection.json` and `test-selection.json` even on failure.
The execution report records tested SHA/base, mode/reason/fallback, Bun version,
complete/always-run/actual file inventories, batch statuses and wall milliseconds.
Native timing files start empty for each invocation; previous measurements never
claim files ran. A failed process stays failed even if evidence is incomplete.

Upload **only** `ci-work-selection.json` as artifact
`ci-work-selection-<run_attempt>`; point CI-esta's completed-run observer at that
name and disable Python-only selection artifact inputs. It uses the existing
`ci-esta/work-selection/v1` schema, separate from the Bun-specific execution
artifact. Source run/attempt/head identity comes from the source workflow, never
the observer. Reporting stays outside validation; keep required jobs/gates strict.
A selection decision is not a success receipt. This adapter never emits reusable
completion evidence; existing receipt actions need independent full-work validation.

Compare selected and full runs on the same checked-out revision and runtime,
with the same inventory, setup, batch count and flags. Retain native inventories,
source run/attempt/head, test wall time, required-gate elapsed time, raw summed
runner-seconds and job counts. Use `ci-esta report --critical-path`; keep observer
cost and cancelled preliminary trials separate. One pair is an observation, not
a universal savings estimate or a billing claim.

## Lessons from web-app

[Web-app #4255](https://github.com/gigaverse-app/gigaverse-web-app/pull/4255)
provided the first consumer implementation. Its same-revision controlled edit
at `dbf00a37ad515124637b7901f3c6c7b71d4414fb` ran 18/657 files in 21.967s versus
380.119s full. App Checks completed in 325s versus 694s; raw runner time was 317s
versus 683s, three jobs each. Both attempt-1 runs passed:
[selected](https://github.com/gigaverse-app/gigaverse-web-app/actions/runs/39924476272),
[full](https://github.com/gigaverse-app/gigaverse-web-app/actions/runs/39924480182).
This source-only parameter rename was a controlled example, not average PR savings.

The reusable interface adds what a second consumer requires: versioned inventory,
always-run contracts, configurable roots/flags/batches, no full-suite receipt for
a subset, and a separate portable report contract. Do not copy the web-app's file
roots, allowlist, worker count or opaque-reader fingerprints into another repo.

## Measured mobile adoption

Keep source-scanning contracts running even when application tests are selected.
[Mobile #3733](https://github.com/gigaverse-app/gigaverse-mobile/pull/3733) uses its
existing discovery API to supply 495 files, including 99 always-run contracts.
A controlled parameter rename in `src/utils/uploadSizeLimit.ts` selected 14
application tests plus all 99 contracts. Both runs passed on the same checked-out
revision `24f45ee5a3385bfe75d7332459c26fb5052a0610`, attempt 1, with Bun 1.4.2,
eight batches, the same lockfile and isolation/parallel flags. The selection base
was `008280aa5933351b3d71954532880bba1cf181da`; neither run reused completion evidence.

| Measurement (lower is better) | [Full control](https://github.com/gigaverse-app/gigaverse-mobile/actions/runs/39929512702) | [Selected](https://github.com/gigaverse-app/gigaverse-mobile/actions/runs/39929509389) |
| --- | ---: | ---: |
| Executed test files | 495 | 113 |
| Test execution wall seconds | 230.806 | 81.849 |
| All required jobs complete, elapsed seconds | 359 | 235 |
| Raw summed runner-seconds | 551 | 422 |
| Started jobs | 3 | 3 |

For this pair, tests took 64.5% less time and required-job completion took 34.5%
less time. Static checks and dependency installation remain; raw runner usage
fell 23.4%. These are observations for one source edit, with hosted setup variance,
not average PR savings or billing measurements. The smaller reduction compared
with web-app reflects a different suite and always-run contract cost.

Each linked run retains `bun-test-execution-1` and `ci-work-selection-1` artifacts.
Native execution inventories confirm every contract ran and the selected set is
a subset of the full 495 files. Reports were collected with
`ci-esta report --critical-path`; the production reporter also consumed both
hosted work-selection artifacts successfully with posting disabled. All three
jobs passed: `test`, `checks`, `run-maestro-es5`. Reporter execution and cancelled
or failed preliminary trials are excluded. Automatic completed-run reporting
starts after the observer workflow reaches the consumer's default branch.

The hosted rehearsal caught a composite-action boundary issue that local module
tests alone could not prove: `github.action_path` was empty when evaluated as a
composite output. The action now exports the planner's resolved filesystem path
from its running step. A regression protects the output, and the consumer's
18 real-Git policy controls passed through that output in both measured runs.
