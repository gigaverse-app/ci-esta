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
imports, aliases and literal dynamic imports through its native bundler graph.
CI-esta combines those edges with [portable dependency declarations](dependency-declarations.md)
and executes the selected files. The adapter owns conservative
admission, exact repository inventory, full fallback, execution and reporting.

The repository owns discovery, global inputs, preload/setup, coverage policy,
explicit full checkpoints, required check names and always-run contracts.
The JSON boundary avoids importing arbitrary consumer code into the planner or
hardcoding a monorepo layout in CI-esta. It also works without GitHub Actions
through the [supported Python API](python-api.md); import nothing outside it.

After the action, native Python policy controls can use its pinned source and
prepared interpreter without installing dependencies in the application:

The same runtime supports `"$CI_ESTA_PYTHON" -m ci_esta check-workflow ...`
and the other CLI commands. It uses checked-out source without installed CI-esta
package metadata; `--version` identifies that source version explicitly.

```yaml
- uses: gigaverse-app/ci-esta/actions/run-bun-tests@v1
  id: tests
  with:
    inventory: ${{ runner.temp }}/bun-inventory.json
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

For separate contract jobs, declare their complete `roots` and `test_patterns`
in the lane configuration as well as `inputs: ["*"]`. Run that lane with
`full: true`. CI-esta keeps these tests in lane membership, but does not build
their dependency graph after the input policy has already admitted the lane.
This preserves full repository contracts without disabling selection for unrelated
functional lanes. Omitting contract membership leaves unclaimed tests and retains
the safe full fallback. A pending lane with an undeclared runtime reader still
runs in full; only already-admitted work can avoid graph analysis.

2. Declare inputs that imports cannot express next to their readers. For example,
`src/catalog.ts.gv-dependency.yaml`:

```yaml
dependencies:
  - inputs: ["//fixtures/catalog/*.json"]
    kind: content
    reason: Loaded from disk by the catalog reader.
```

Run `ci-esta bun-declarations --root <test root>` first: it lists every reader to
declare, declarations no test reaches and directories to merge, in one run
([audit](dependency-declarations.md#start-with-the-audit)).

The format and parser are pytest-selective's, shared with Python projects through
the lightweight `selective-deps` package. Prefer one directory manifest per
directory; [authoring rules](dependency-declarations.md#author-one-manifest-per-directory)
cover which files need one, `{stem}` sibling pairs and reviewed readers with no inputs.
`kind: import` follows the declared input's imports (use it for executed scripts),
and `kind: content` reads only its bytes. No reader hashes or repository-wide exception registry are
needed. A content change selects the reader's dependent tests, not every test.

Declarations are reviewed input contracts, not automatic discovery of every runtime
read. Declare computed imports, filesystem reads and subprocess inputs that the
native graph cannot see. Keep full checkpoints and separate policies for external
state. Invalid declarations fail with their source location. Environment changes,
preload dependencies, removed files and unmodeled non-import inputs run the full
inventory. The legacy `policy` JSON is deprecated and warns in Actions;
[migrate it to declarations](dependency-declarations.md#migrate-from-a-reviewedreaders-policy).

3. Invoke after dependency installation and inventory generation:

```yaml
- run: bun run test --inventory > "$RUNNER_TEMP/bun-inventory.json"
- uses: gigaverse-app/ci-esta/actions/run-bun-tests@v1
  with:
    inventory: ${{ runner.temp }}/bun-inventory.json
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
`validated-head` proves a `pull_request` merge commit, whose second parent is the PR
head. A workflow triggered by `push` tests the head itself: pass the earlier green head
as `base` and omit `validated-head`, because ancestry is then the proof. Passing
`validated-head` there fails the merge check and runs the full suite.
Unreferenced documentation must not start tests. Do not apply a whole-suite coverage floor
to a subset or lower a floor to make it pass. Coverage lanes should stay full.

`shards` means sequential fresh-process batches on one runner, not a matrix.
The adapter partitions the complete sorted inventory once. On a full run each
batch runs unchanged; on a scoped run each batch executes its selected files and
always-run contracts. Both preserve the supplied isolation/parallelism
flags. Empty groups never invoke Bun. All batches finish and any failed batch
keeps the final exit code nonzero. Supported flags are isolation, parallelism,
timeout, concurrency, seed, randomization and dots; selection/output flags are
owned by the adapter. There is no retry of a failed selected test as a full run
that could conceal its failure.

Missing/invalid history, an invalid recorded merge parent, dirty tracked files, untracked inputs,
unknown inputs and renames/deletions execute
the full inventory. Optional persisted plans are recomputed at execution; stale,
missing or forged reuse plans fall back to full. An explicit full override wins.
Keep generated inventory/reports outside the worktree (for example RUNNER_TEMP).
Unsupported runtime versions and missing inventory fail visibly.

## Preloads and retained scheduling history

Use the shared runner for compatibility suites as well as the default suite:

```yaml
- uses: gigaverse-app/ci-esta/actions/run-bun-tests@v1
  with:
    inventory: ${{ runner.temp }}/zod4-inventory.json
    preloads: '["scripts/zod-4-runtime.preload.ts"]'
    args: '["--isolate"]'
    shards: '6'
    timing-history: ${{ runner.temp }}/bun-history/zod4.json
```

Each batch also writes a JUnit report (`junit-*.xml`) into the output directory. Upload it, and
the next run can [re-run what failed first](failed-first.md) through `previous-failures`: those
files run in their own first batch, even when the change does not reach them, and by default the
run stops there if they still fail.

`preloads` accepts repository-relative files, preserving their order before every
Bun batch. A changed preload or transitive preload input forces full execution.
Declare its non-import inputs using the same sidecar or directory-manifest format.

Restore and save `timing-history` with the repository's cache policy, separating
runtime, OS, lockfile and compatibility lane. It must live outside the checkout.
The runner balances complete files using retained native Bun millisecond costs;
missing or malformed history retains deterministic batching. Fresh per-batch
timing files alone prove execution. Successful complete execution updates costs
for observed files and prunes files outside the current inventory. Failure does
not update history. Historical costs never grant completion receipts or skipped
work. Measure batch/setup overhead before claiming elapsed-time savings.

## Whole-lane planning

The plan artifact's `selected` list names test files reached by the Python and Bun dependency
graphs. A changed Bun preload includes the files that use it. This count is a lower bound for
runner sizing. A full checkpoint, a previous failure or a workflow rule can admit a lane
without enumerating its files. Use `lanes` for admission and the execution report for actual coverage.

The adapter above narrows files inside one `bun test` run. To skip whole jobs, use
[`plan-work`](actions.md); its lanes come from your workflow, or from a lane file whose
roots hold your Bun tests. The planner asks Bun for its module graph, so `plan-work`
installs Bun itself when the repository has Bun-style test files (`*.test.ts`,
`*_spec.mjs`, ...) and no `bun` is on `PATH`, pinned by `.bun-version`, `.tool-versions` or
`packageManager` in `package.json` when one exists. Without Bun the planner cannot see
which tests a change reaches and runs every lane holding Bun tests, even for a
documentation change:

```yaml
select-tests:
  runs-on: ubuntu-latest
  outputs:
    lanes: ${{ steps.plan.outputs.lanes }}
    selection-base: ${{ steps.plan.outputs.selection-base }}
  steps:
    - uses: actions/checkout@v7
      with:
        fetch-depth: 0
    - id: plan
      uses: gigaverse-app/ci-esta/actions/plan-work@v1
```

Edits to a downstream workflow that subscribes to completed runs (optionally
also to manual dispatch) select the Bun lanes and individual tests that depend on its YAML. For
example, changing where a reporter runs can skip application tests while a
test that reads that workflow still runs. Both revisions must have these
triggers. Explicit lane inputs and previous test failures still select work.

In the job that runs Bun, add `needs: select-tests` and pass the planner's commit
to the file selector after installing Bun and generating the inventory:

```yaml
- uses: gigaverse-app/ci-esta/actions/run-bun-tests@v1
  with:
    inventory: ${{ runner.temp }}/bun-inventory.json
    base: ${{ needs.select-tests.outputs.selection-base }}
```

GitHub can build a PR merge after the target branch advances. The planner checks
the merge's second parent against the event's PR head before using its first
parent as the base. Passing that output keeps target-branch changes out of both
plans. Forward an empty output unchanged so Bun executes the full inventory on
a full checkpoint or missing history. If receipts depend on this base, include it
in their execution context and disable reuse when it is empty. A separate comparison against a previously
tested merge still uses that receipt's commit and `validated-head`.

Install Bun before `plan-work` yourself (`oven-sh/setup-bun`) only to pin a version kept
somewhere else; `plan-work` then uses that one.

Every job that re-plans lanes through the Python API or CLI also needs Bun when its
inventory includes Bun-style or Node test files. Runtime setup is job-local: installing
Bun in `select-tests` does not install it in a routing-regression or validation job.
Use `oven-sh/setup-bun@v2` before those calls, with the same repository version file.
This supplies the module-graph planner; the repository keeps its original Node/Jest
runner for executing those tests. Missing Bun remains a full-lane fallback, including
for documentation-only probes, so inspect the plan's reasons instead of treating that
fallback as a dependency edge.

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
that lane whether or not a test imports it. Inside a selected lane, `run-bun-tests` uses the same native graph and declarations to
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
    base="<full comparison SHA>",
    output_directory=Path("/tmp/bun-execution"),
))
raise SystemExit(result.exit_code)
```

Install `ci-esta` for this native API; the Python selector extra is not needed for
the Bun graph and portable declarations. Whole-lane planning still uses
`ci-esta[selection]`. The GitHub action uses the
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

The `ci-esta adoption` inventory recognizes `run-bun-tests` as native test
execution and reports its `timing-history` input separately from pytest history
keys. The input alone does not prove persistence: verify a successful run saves
the history and a subsequent run restores it before execution.
