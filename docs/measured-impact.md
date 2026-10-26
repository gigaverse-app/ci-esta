# Show what your CI optimization changed

Lead the pull-request report with the work executed or avoided and a measured
before/after comparison. Keep the timeline available for diagnosis inside its
closed section. A fast test subset is useful evidence only when the full control
still passes and the comparison preserves the execution contract.

## Keep benchmark evidence in the sticky

Pass `impact-comparisons-json` to the reporting action or reusable report workflow.
Each pair specifies exact source run IDs, attempts and head SHAs. CI-esta reads
their timings from GitHub, checks successful completion and matching identities,
and links both measurements. No caller-supplied duration or percentage is trusted.

```yaml
with:
  impact-comparisons-json: |
    [{"label":"Affected tests: gate elapsed", "metric":"gate", "job":"Validation gate",
      "context":"One full/selected pair with the same runtime and worker count.",
      "before":{"run_id":123,"run_attempt":1,"head_sha":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"},
      "after":{"run_id":124,"run_attempt":1,"head_sha":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"}}]
```

Replace the example IDs and SHA with your actual control and selected run.
`metric` accepts `gate` (creation to named gate, or attempt start on retries),
`runner` (summed job time for that exact attempt), or `steps` (sum of the unique
exact step names in `steps`, within the named `job`). Zero-second API intervals
display as `<1s`; missing timestamps display as unavailable.

The default `comparison: same_head` requires identical heads. This verifies source
identity, not experimental equivalence: also verify the checked-out merge SHA,
base, dependencies, services, runtime and worker count. Explain those controls in
`context`. Use `comparison: workflow_change` for before/after revisions that
change CI itself, with an explicit limitation on attribution. Historical benchmark
rows remain labelled historical; they never imply that every new run saved the
same time. Expired/inaccessible evidence produces an unavailable row, not a zero.

Use at most 12 meaningful rows. A step, runner total and gate elapsed overlap:
never sum their savings. Reporter overhead and failed/cancelled attempts are
separate costs. CI-esta shows latest-attempt latency separately from all-attempt
runner usage. Retry only the failed workflow when independent successful checks
are still valid.

## Bun and pytest use the same reporting boundary

The [Bun adapter](bun-test-selection.md) emits structured execution evidence in
`ci-work-selection.json`: full/scoped/unaffected/reused mode, result, complete
inventory size, observed executed files, test wall time, runtime, tested commit,
selection base and always-run contracts. The sticky shows counts and timing;
the full inventory stays in JSON with a bounded expandable preview.

An unknown inventory is not zero executed files. A successful process without
complete full-suite or always-run evidence is marked incomplete. Reused validation
must carry its receipt and cannot claim freshly executed tests. File-count
reductions are not converted to time savings. Only measured benchmark pairs
support the before/after time table.

Custom Python orchestration can call `work_selection_report` from
`ci_esta.testing.bun.report` with `BunExecution` and `ReportContext` from
`ci_esta.testing.bun.models`. Keep the tested merge commit in
`execution.tested_sha`; it may differ from the PR head. This helper only formats
evidence and cannot authorize a skip. Python repositories retain
pytest-selective's graph and explanation contracts; base reporting needs no
pytest installation.

Alternatively use `actions/report-bun-tests` with `execution-file` pointing
to your runner's execution JSON and `output-file: ci-work-selection.json`. Invoke
it with `if: always()` after the runner, then upload the output even on failure.
It converts evidence only, so an existing runner can keep memory sampling,
isolation and execution policy without installing another test framework.

## Measure cache overhead too

A cache hit is not automatically a speedup. Include restore, save, key evaluation
and mandatory verification in the comparison. Recursive `hashFiles` expressions
can traverse installed dependencies. Compute the identity once before dependency
installation and reuse the output in both restore and save keys:

```yaml
- id: cache-inputs
  shell: bash
  run: echo "config=${{ hashFiles('bun.lock', '.bun-version', '**/tsconfig*.json') }}" >> "$GITHUB_OUTPUT"
```

Keep OS, architecture, runtime/ABI and lock/config identity in the cache key.
Always run the compiler or locked dependency synchronization after restoring.
For Python, use [setup-cached-uv](environment-cache.md), including its broken
environment repair and locked synchronization, rather than copying cache logic.

For Bun CLI tools, verify the actual installation directory. With Bun 1.4.2 on
Linux, `bunx firebase-tools@15.29.0` installs the executable tree under
`${TMPDIR:-/tmp}/bunx-$(id -u)-firebase-tools@15.29.0`. Caching only Bun's package
download directory did not preserve that installed tree. Pin the tool version,
include the Node ABI and Bun version in its cache key, and still execute its
version/preparation command and real smoke test. Confirm the directory again
when upgrading Bun; this is a measured runtime detail, not a stable public API.

## Avoid unnecessary runs without weakening gates

Remove broad `labeled`/`unlabeled` validation triggers when ordinary label changes
have no effect on the work. Keep a documented immediate full-run mechanism:
manual full dispatch or explicit `full: 'true'` input. PR/push reruns preserve
selection. A `test:full` label present in the event can still force the
next revision's full validation. Preserve dedicated label-driven security and
drill workflows that actually use the event.

A newly added aggregate gate is insufficient if branch protection still requires
an older job. Make the existing required job fail when its planner fails, even
if fallback tests ran successfully. Missing proof runs the full suite; it does
not turn a failed required planner green.

## Measured web example

These observations motivated the recipe. They are individual measurements, not
expected averages for other repositories. See the
[implementation and controls](https://github.com/gigaverse-app/gigaverse-web-app/pull/4255)
and [cache correction](https://github.com/gigaverse-app/gigaverse-web-app/pull/4256).

| Scenario | Before | After | Scope |
| :-- | --: | --: | :-- |
| Affected tests, gate elapsed | 694s | 325s | Same revision, full versus 18 of 657 files; 2 workers |
| Unchanged validation reuse, gate elapsed | 801s | 269s | Same head and tested merge tree; other checks still ran |
| Compiler cache restore/save steps | 64s | 2s | Key computation moved before install; different workflow revisions |
| Firebase CLI preparation | 82s | <1s | Same head, attempts 1 and 2; real build/emulator smoke retained |

The affected pair is [full](https://github.com/gigaverse-app/gigaverse-web-app/actions/runs/39924480182)
and [selected](https://github.com/gigaverse-app/gigaverse-web-app/actions/runs/39924476272).
Reuse is [full](https://github.com/gigaverse-app/gigaverse-web-app/actions/runs/39927187186)
and [reused](https://github.com/gigaverse-app/gigaverse-web-app/actions/runs/39928908350).
The cache fix is [after](https://github.com/gigaverse-app/gigaverse-web-app/actions/runs/39929778876).
Firebase is [cold](https://github.com/gigaverse-app/gigaverse-web-app/actions/runs/39927187291/attempts/1)
and [warm](https://github.com/gigaverse-app/gigaverse-web-app/actions/runs/39927187291/attempts/2).

The two reporting workflows consumed 20 and 24 runner-seconds. A later unrelated
APT download stall consumed 766 runner-seconds before cancellation and retry.
That cost belongs in iteration accounting, not in the successful paired savings.
