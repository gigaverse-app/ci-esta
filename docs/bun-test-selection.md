# Affected tests with Bun

Use this adapter when the repository actually runs `bun test`. TypeScript and
React identify source languages and libraries, not the test runner. A project
using Bun only to install packages may still run Jest, Vitest or Playwright.
Keep those runners and their native selection contracts. Python pytest projects
continue to use pytest-selective; CI-esta does not build a second import graph.

## Contract and ownership

The portable action is `gigaverse-app/ci-esta/.github/actions/run-bun-tests`.
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
- uses: gigaverse-app/ci-esta/.github/actions/run-bun-tests@<reviewed-commit>
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
