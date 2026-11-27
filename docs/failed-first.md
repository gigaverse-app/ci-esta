# Re-run what failed first

When a pull request is red, the next push has one urgent question: *are the tests that
failed fixed now?* CI-esta answers it first. It reads which test files failed in the
branch's previous run, runs those files before anything else, and by default stops as
soon as they fail again. A still-red PR gets its answer from one small batch instead of
a full run; a fixed one goes on to the rest of the suite.

It also closes a selection gap. Selection runs the tests a change can reach. A fix in a
helper, a fixture or an unrelated module may not reach the test that failed, so
selection alone would never re-run it and the PR could look green while that test is
still broken. Previous failures are always re-selected, whatever the change touches.

| Without failed-first | With failed-first |
| --- | --- |
| A still-red push runs every selected batch before reporting the same failure | The previous failures run first; the run stops after that batch when they fail again |
| A fix that does not touch the failed test lets selection skip it | The failed files run on every push until a run passes them |
| The PR report lists files | The PR report leads with *now pass* or *still fail* |

It works for pytest and Bun, from the JUnit reports both runners write.

## Bun with `run-bun-tests`

`run-bun-tests` writes a JUnit report per batch (`junit-*.xml`) into its output
directory. Upload that directory, as the [Bun guide](bun-test-selection.md) shows, then
read the previous run's reports before running:

```yaml
- id: failures
  uses: gigaverse-app/ci-esta/actions/resolve-previous-failures@v1
  with:
    artifact-pattern: bun-test-${{ env.LANE }}-*   # the artifact your lane uploads
    test-files: bun
- uses: gigaverse-app/ci-esta/actions/run-bun-tests@v1
  with:
    inventory: ${{ runner.temp }}/bun-inventory.json
    previous-failures: ${{ steps.failures.outputs.failures-file }}
    # stop-on-previous-failure: 'false'   # run every batch even when they still fail
```

The job needs `actions: read` to list runs and download their artifacts.

When `plan-work` decides which whole lanes run, give it the same file (resolved with an
`artifact-pattern` that matches every lane's reports). A lane that owns a previous failure
runs even when the push reaches none of its tests, with the reason `previous failure: <file>`:

```yaml
- id: failures
  uses: gigaverse-app/ci-esta/actions/resolve-previous-failures@v1
  with: {artifact-pattern: 'bun-test-*', test-files: bun}
- uses: gigaverse-app/ci-esta/actions/plan-work@v1
  with:
    config: .github/test-lanes.json
    base: ${{ needs.base.outputs.base }}
    previous-failures: ${{ steps.failures.outputs.failures-file }}
```

A custom runner that calls `python -m ci_esta.testing.bun.cli run --json-input` passes
the same fields in its request: `previous_failures` (a list of repository-relative test
files) and `stop_on_previous_failure`.

## pytest

`resolve-previous-failures` with `test-files: pytest` reads the previous run's pytest
JUnit artifacts. Add its file list to the changed files your selector reads, so the
failed files are selected, and run them first with `ci-esta-pytest canary-run`:

```yaml
- id: failures
  uses: gigaverse-app/ci-esta/actions/resolve-previous-failures@v1
  with:
    artifact-pattern: pytest-results-*
    junit-pattern: '**/junit-*.xml'
    test-files: pytest
- name: Run previous failures first
  if: ${{ steps.failures.outputs.has-failures == 'true' }}
  run: uv run ci-esta-pytest canary-run "${{ steps.failures.outputs.failures-file }}" -- -n 0
```

`canary-run` drops files the full suite would not run (deleted, unimportable or fully
deselected), so a stale failure can never block a retry. Repositories that already find
their failed run with `resolve-pytest-evidence` can keep using `pytest-failure-canary`
directly; both share the same planner.

### Marking red PRs

`pytest-canary-pr-state` adds or clears a `pytest-red` label (repositories use their own
name, such as `ci:pytest-red`) only when the tested commit is still the PR head. Any run
may mark a PR red from its JUnit evidence; only the complete, authoritative matrix may
clear it. Workflows can then run the canary only on labeled PRs.

## What it guarantees

- **A stopped run is never a pass.** When the previous failures fail again and the run
  stops, the skipped batches make the execution incomplete; it reports *incomplete* and
  fails, and no completion receipt can be issued for it.
- **Only real, current test files are re-run.** Deleted, renamed or escaping paths are
  dropped; a file outside the current inventory is ignored.
- **No evidence is not an error.** With no previous failed run, no matching artifacts or
  an unreadable report, the failures file is empty and selection proceeds as usual.
- **Unknown failures stay unknown.** A batch that fails without naming a failed test (a
  file that does not load) records its failed files as unknown, never as none.
- **Files run once.** Previous failures leave the ordinary batches, so a fix is not
  executed twice.

`resolve-previous-failures` reads the newest completed run of the same workflow on the
same branch, skipping cancelled runs (concurrency cancels superseded pushes). After a
green run there is nothing to re-check. Reruns of failed jobs already repeat exactly
those jobs, so the action does not look at earlier attempts of the current run.

If a parent workflow dispatches the tests to a worker, pass the parent's run ID
as `parent-run-id`. The worker must test the same commit in the same repository.
CI-esta then reads the earlier results for the parent's workflow and branch. Keep
the worker's JUnit reports available on the parent run so the next push can find them.

## Adoption and opting out

`ci-esta adoption` suggests `failed-first` when a repository runs tests and nothing
re-checks previous failures, or when a `run-bun-tests` step does not receive
`previous-failures`. To opt out, record the decision with its reason:

```yaml
# .github/ci-esta-reviewed.yaml
reviewed:
  - suggestion: failed-first
    evidence: .github/workflows/tests.yml
    reason: Every run is a full run that finishes in under a minute.
```

## Rerun the failures on your machine

The steps above re-run failures in CI. To get the same answer before you push, give a
failed log to `ci-esta retry`. It prints one command per tool, naming only what failed:

```sh
gh run view 123456 --log-failed | uvx --from 'ci-esta>=1,<2' ci-esta retry -
```

```text
pytest 'tests/test_a.py::test_param[a - b]' tests/test_a.py::TestK::test_m tests/test_collect.py
bun test ./tests/broken.test.ts ./tests/unit/math.test.ts
lake build +Lib.Broken
```

| Tool | What it reads in the log | What it prints |
| --- | --- | --- |
| pytest | `FAILED` and `ERROR` lines of the short test summary | the test ids, and the file for a collection error |
| Bun | `(fail)` lines and errors outside a test, under each file's heading | the test files |
| Lake | failed build jobs and `error:` lines with a Lean source | the modules, as `+Module` targets |

Run it in the directory the failed command ran in, or pass `--repo`. A saved log file works
in place of `-`. Anything the log names that is not in your checkout is listed on standard
error and left out of the command. Add your own runner in front, such as `uv run`.

The command only reads the log and prints. A passing rerun shows that those tests pass
now; the full suite in CI still decides the pull request.
