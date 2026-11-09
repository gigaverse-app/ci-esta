# Affected tests with Bun

See the [selection and evidence policy](test-selection-policy.md) for the scenario map, tested Git identities, reruns and Python/JavaScript setup.

Use this adapter when the repository actually runs `bun test`. TypeScript and
React identify source languages and libraries, not the test runner. A project
using Bun only to install packages may still run Jest, Vitest or Playwright.
Keep those runners and their native selection contracts. Python pytest projects
continue to use pytest-selective; CI-esta does not build a second import graph.

## Contract and ownership

The public action is `gigaverse-app/ci-esta/actions/run-bun-tests`; see
[entry-point availability](actions.md) for the published `@v1` entry point. The caller supplies Bun >=1.4.2 <2 and application
dependencies. CI-esta owns the adapter in Python and automatically prepares its
locked, isolated tool environment, shared with reporting and timing actions.
It does not use or change the application virtual environment or lockfile. Bun owns static/transitive
imports, aliases and literal dynamic imports through
[`--changed=<base>`](https://bun.sh/blog/bun-v1.4). The adapter owns conservative
admission, exact repository inventory, full fallback, execution and reporting.

The repository owns discovery, global inputs, preload/setup, coverage policy,
explicit full checkpoints, required check names and always-run contracts.
The JSON boundary avoids importing arbitrary consumer code into the planner or
hardcoding a monorepo layout in CI-esta. It also works without GitHub Actions:
import `SelectionRequest` / `RunRequest` from `ci_esta.testing.bun.models`,
`plan_affected_tests` from `ci_esta.testing.bun.selection`, and `run_bun_tests`
from `ci_esta.testing.bun.execution`.

After the action, native Python policy controls can use its pinned source and
prepared interpreter without installing dependencies in the application:

```yaml
- uses: gigaverse-app/ci-esta/actions/run-bun-tests@v1
  id: tests
  with:
    inventory: ${{ runner.temp }}/bun-inventory.json
    policy: .github/test-selection.json
- name: Verify repository policy
  env:
    PYTHONPATH: ${{ steps.tests.outputs.python-path }}
  run: '"$CI_ESTA_PYTHON" .github/scripts/test_selection.py'
```

The `python-path` output replaces `selection-module`. The JavaScript imports
`selection.mjs`, `run.mjs` and `work-report.mjs` have been removed. Migrate policy
controls to the Python API above, and report custom execution with
`actions/report-bun-tests` or `ci_esta.testing.bun.report.work_selection_report`.
This maintainer-approved migration stays on `@v1`. Before that alias advances,
migrate any `selection-module` consumers to `python-path` and native Python
imports. Pin the reviewed migration commit until publication. The immutable
v1.6.2 tag and existing commit pins retain the old interface for rollback.

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
- uses: gigaverse-app/ci-esta/actions/run-bun-tests@v1
  with:
    inventory: ${{ runner.temp }}/bun-inventory.json
    policy: .github/test-selection.json
    shards: '8'
    args: '["--isolate","--parallel"]'
    output-directory: ${{ runner.temp }}/bun-test-selection
```

The inventory command is an adopter API, not a built-in Bun flag. Fetch history.
The action defaults `base` to the PR base or push `event.before` and `full` to
`auto`: ordinary PRs/pushes and their reruns stay selective; manual, scheduled,
release and `test:full` requests run full. Manual measurements can explicitly
set a base and `full: false`. Reruns execute their selected scope without receipt
reuse. For validated incremental PR selection, use the
[complete tested-merge workflow](../examples/bun-tests/workflow.yml) and pass
`validated-head` with its recorded merge; missing proof retains a full checkpoint.
Unreferenced documentation must not start tests. Do not apply a whole-suite coverage floor
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

Missing/invalid history, an invalid recorded merge parent, dirty tracked files, untracked inputs, malformed policy,
unknown paths, symlinks, renames/deletions and changed reader fingerprints execute
the full inventory. Optional persisted plans are recomputed at execution; stale,
missing or forged reuse plans fall back to full. An explicit full override wins.
Keep generated inventory/reports outside the worktree (for example RUNNER_TEMP).
Unsupported runtime versions and missing inventory fail visibly.

## Whole-lane planning

The adapter above narrows files inside one `bun test` run. To skip whole jobs, use
[`plan-work`](actions.md) with a lane file whose roots hold your Bun tests. Install Bun in
the planning job first (`oven-sh/setup-bun`), because the planner asks Bun for its module graph:

```yaml
select-tests:
  runs-on: ubuntu-latest
  outputs:
    lanes: ${{ steps.plan.outputs.lanes }}
  steps:
    - uses: actions/checkout@v7
      with:
        fetch-depth: 0
    - uses: oven-sh/setup-bun@v2
    - id: plan
      uses: gigaverse-app/ci-esta/actions/plan-work@v1
      with:
        config: .github/test-lanes.json
```

Bun's bundler metafile lists what each test bundles: its imports followed transitively,
including `require`, side-effect and dynamic `import()` calls with literal paths, and text,
JSON, style and asset imports. A changed file selects the lanes of the tests that bundle it,
so a README no test imports selects nothing. CI changes reach lanes through the same workflow
graph as Python lanes.

The planner needs no `node_modules`: packages stay external, and every import that names a
repository file by more than a relative path is resolved with Bun's own resolver. That covers
tsconfig `paths` aliases (`@/x`), Vite-style query imports (`./icon.svg?react`, `./dock.css?raw`,
`@/hero.png?url`), whose file is the input, and workspace packages imported by name
(`@scope/lib/util`), which only a `node_modules` link resolves at runtime. A local dependency
declared by path in `package.json` (`"stats": "./modules/stats"`, `file:` or `link:`) is treated
like a workspace package. Without `node_modules`, such a package resolves from its directory,
ignoring an `exports` map; an import that resolves neither way fails the graph rather than losing
an edge. An untracked file in the checkout, such as generated code, never changes, but the files
it imports still reach the tests that import it.

React Native platform files work too. Bun ignores tsconfig `compilerOptions.moduleSuffixes`, so
the planner applies the suffixes the root `tsconfig.json` declares (an `extends` chain is not
followed): `./Signin.provider`, with only `Signin.provider.ios.ts` and `Signin.provider.android.ts`
on disk, makes both files inputs of the importing test, as does an aliased or directory import
(`@/video/view` naming `view/index.ios.tsx`). When an unsuffixed file also exists, it and every
suffixed variant are inputs. A relative path into `node_modules`
(`../../node_modules/pkg/src/file.js`) names a package file, so like a bare package import it is
covered by the lockfile and needs no install. Bun's `bun:` and `node:` built-ins, including the
`bun:wrap` import Bun records for a computed `require`, are not files.

A test preload (`preload` in any `bunfig*.toml`, top-level or under `[test]`) runs before every
test without being imported. The planner cannot see which `--config` a lane passes, so a change to
any preload, or to anything a preload bundles, reaches every Bun lane.

| Change | Bun lanes |
| --- | --- |
| A module a test imports, directly or transitively, by any of the paths above | that test's lanes |
| A file imported as text, JSON, style or asset, with or without a `?query` | that test's lanes |
| A test preload, or anything it bundles | every Bun lane |
| A deleted test | its lane |
| `package.json`, `bun.lock`, `bunfig*.toml`, `tsconfig*.json` | every Bun lane |
| A graph Bun cannot build, or no Bun on the runner | every Bun lane |
| Documentation and data no test imports | nothing |

One import Bun cannot resolve fails the whole graph, so every Bun lane runs: the test that holds
it would fail anyway. The fallback reason quotes the first line of Bun's output that reads as an
error, such as `error: Could not resolve: "./missing" (src/a.ts:1)`, not a warning printed before it. A file read at runtime by path (`Bun.file("fixtures/x.json")`), a script a
test spawns, or a computed `import(name)` is invisible to the module graph; import it, keep it
under the lane's roots, or list it in the lane's `inputs`. A change under a lane's roots selects
that lane whether or not a test imports it. Inside a selected lane, `run-bun-tests` and `--changed`
still narrow the files that run.

The graph is built in one `Bun.build()` call per round, with the entry list in a file rather
than on the command line, so the number of tests has no command-line limit. On
[web-app](https://github.com/gigaverse-app/gigaverse-web-app) at `deac0ab2a`, the graph over
809 Bun test files and 3 preloads reached 3,260 files on a Windows workstation in 0.7 to
0.8 s with Bun 1.4.2 (6.6 s on a cold first run) and 3.1 to 3.9 s with Bun 1.3.14. Both
versions produced the same 110,474 edges.

## Direct Python use

```python
from pathlib import Path
from ci_esta.testing.bun.execution import run_bun_tests
from ci_esta.testing.bun.models import RunRequest

result = run_bun_tests(RunRequest(
    cwd=Path("/checkout/app"), inventory_file="/tmp/bun-inventory.json",
    policy_file=".github/test-selection.json", base="<full comparison SHA>",
    output_directory=Path("/tmp/bun-execution"),
))
raise SystemExit(result.exit_code)
```

Install `ci-esta[selection]` in the tool environment. The GitHub action uses the
pinned checkout and lockfile. Selection policy, Git proof, inventory checks,
process orchestration and report models live in Python; Bun owns its native
import traversal and test process. Python's native dependency graph remains in
pytest-selective. Extra tool setup and Python process startup are costs to measure,
not evidence of a CI speedup.

## Evidence and reports

The sticky now includes structured executed/full file counts, test wall time,
runtime, mode/result, and a collapsed inventory. See
[measured impact](measured-impact.md) to add verified full/selected benchmark pairs
without mistaking file-count reduction for a measured time saving.

Upload `execution-selection.json` and `test-selection.json` even on failure.
The execution report records tested SHA/base, mode/reason/fallback, Bun version,
complete/always-run/actual file inventories, batch statuses and wall milliseconds.
Native timing files start empty for each invocation; previous measurements never
claim files ran. A failed process stays failed. Missing timing evidence, missing
files in a full run or missing always-run contracts also fail the action, even
when Bun exits zero. The executor and reporter share the same completeness rule.

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
