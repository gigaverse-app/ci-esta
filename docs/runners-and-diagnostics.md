# Runner capacity, shard pools and hang diagnostics

Choose runner capacity and test concurrency separately. A larger runner helps only
when the critical path uses its CPU or memory. Record queue time, dependency and
service setup, slowest shard, summed runner time and cgroup throttling before
changing either. `nproc` alone does not establish the available CPU quota.

## One large runner

Gigaverse backend uses its organization-provisioned `16vcpu-runner` label with up
to twelve concurrent serial pytest processes. The label is consumer configuration,
not a label GitHub provides to every repository. Its October 8 measurements favored
twelve over fourteen shards; this is a historical recipe, not a universal optimum.
Retain the consumer's database, Redis, temporary directory and artifact isolation
for each shard. Start services and restore the environment alongside planning when
those jobs are independent, and keep test execution independent of image builds.

```bash
# Install CI-esta at a compatible release version in the test environment.
export CI_TEST_RESOURCE_OBSERVABILITY=true
ci-esta-resources ci-esta-pytest run-local --shards 12 --log-dir shard-logs -- \
  bash deployment/scripts/ci/run_unit_test_shard.sh
```

`run-local` supplies each command's `GV_PYTEST_SHARD_INDEX` and `GV_PYTEST_SHARD_COUNT`.
Use pytest-selective's duration-balanced assignments inside each process. Always
run the completion gate against the planned global shard count; resource logs
and successful subprocess startup are not evidence that tests completed.

`run-local` prints each shard's result as it finishes. Every 60 seconds it also
prints the log tail of shards still running, so a blocked first shard cannot hide
other results or watchdog traces before a job timeout. Tune this interval with
`--progress-interval-seconds`; full logs remain in `--log-dir`.

## Pools across standard or larger runners

The same planner supports sharding inside one runner and distributing shards
across several runners. Runner capacity does not change which tests are selected.

| Layout | Global shards | Shards per runner | Runner jobs |
| --- | ---: | ---: | ---: |
| One larger runner | 16 | 16 | 1 |
| Several standard runners | 16 | 2 | 8 |
| Several larger runners | 55 | 16 | 4 |

Set the consumer's `runs-on` to its provisioned runner label, and choose the
per-runner process count from measurements. A 16-vCPU runner does not imply that
16 processes is always optimal. Keep the global shard count bounded by the
consumer's intended runner budget; 64 shards at two per runner requests 32 jobs,
which can add substantial queue and repeated setup time.

Public repositories receive free standard GitHub-hosted runner time. Larger
runners are billed for both public and private repositories and do not use
included minutes. See [GitHub's larger-runner billing rules](https://docs.github.com/en/actions/concepts/runners/larger-runners#billing).

Plan bounded, consecutive ranges once, then execute the returned assignment:

```bash
ci-esta-pytest pools --shards 55 --shards-per-runner 2 --github-output "$GITHUB_OUTPUT"
```

For a planning job without application dependencies, use the composite action
`plan-runner-pools` at a compatible release version with inputs
`shards` and `shards-per-runner`. It exposes the same outputs as the CLI.

The `pools` output is a JSON array suitable for a matrix's `pool` axis. Each object
contains a stable string `id`, `shard_count`, `first_shard` and `last_shard`. The
`count` output counts runners. The last pool may be smaller. Each global shard
appears exactly once, including when fewer shards exist than a runner's capacity.

```yaml
strategy:
  fail-fast: false
  matrix:
    pool: ${{ fromJSON(needs.plan.outputs.pools) }}
steps:
  # Consumer checkout, environment and service setup go here.
  - name: Execute this pool
    env:
      SHARDS: ${{ matrix.pool.shard_count }}
      FIRST: ${{ matrix.pool.first_shard }}
      LAST: ${{ matrix.pool.last_shard }}
    run: >-
      ci-esta-pytest run-local --shards "$SHARDS"
      --first-shard "$FIRST" --last-shard "$LAST" --log-dir shard-logs --
      bash deployment/scripts/ci/run_unit_test_shard.sh
```

Use `matrix.pool.id` for job/artifact/output identities. Pass the same range to the
pool completion gate and retain the aggregate check covering every planned pool.
Do not recompute ranges in another shell step. Runner labels, concurrency limits,
service credentials, costs and application fixtures remain consumer-owned.

## Resource and pytest diagnostics

`ci-esta-resources COMMAND ...` is Linux-only. With
`CI_TEST_RESOURCE_OBSERVABILITY=true`, it reports CPU capacity, cgroup limits and
counters, load, top processes, optional Docker stats, and `/usr/bin/time -v`.
`CI_TEST_RESOURCE_OBSERVABILITY_INTERVAL_SECONDS` defaults to 20. Without opt-in
it directly executes the command. It preserves exit status and forwards
termination to the command group while cleaning up the resource monitor.

Enable pytest progress dumps explicitly:

```bash
PYTEST_HANG_WATCHDOG_SECONDS=90 PYTEST_POST_SESSION_GRACE_SECONDS=15 \
  python -m pytest -p ci_esta.testing.pytest_watchdog
```

The daemon watchdog dumps thread names and stacks after a progress deadline. A
mid-test timeout only diagnoses. After session finish, a leaked non-daemon thread
cannot hold the process indefinitely: the watchdog exits with the session's current
status, including failures added by late hooks. Use this only in standalone CI
pytest processes, not embedded `pytest.main()` calls. Application executor cleanup
still belongs in the consumer's shutdown hooks. Zero timeout disables the plugin.

## Source-tree and workflow rules

Use [import-linter](https://import-linter.readthedocs.io/en/stable/contract_types/)
for normal forbidden-import, layer and independence contracts. CI-esta uses its
standard forbidden contracts to keep generic diagnostics independent of pytest
and shard assignments independent of execution. Backend already uses import-linter
for its module contracts. Neither needs another implementation of those rules.

Keep CI-esta's recursive filesystem boundary checker where a project also needs
paired test/source trees, nested common scopes, namespace-directory discovery,
conftest exceptions or importer-specific privileges. An import-linter graph is
not automatically equivalent: during migration it did not discover AI's nested
`gv.ai.common` namespace beneath regular packages. Do not delete that checker
until a real package graph and the existing violation corpus prove equivalence.

Use actionlint for workflow syntax, expressions, action inputs and runner-label
validation. Keep completion/evidence gates and repository-specific policy checks:
valid YAML cannot prove that every required test actually ran.

## Bun capacity and validated revisions

`report-bun-tests` accepts optional `cpuCount`, `workers` and `runnerLabel` in
execution evidence. The report shows the observed CPU count and configured worker
limit above its collapsed sections. A worker limit is not measured occupancy.
Custom runner labels require a `runner-sku-rates-json` mapping to a catalog SKU,
for example `{"runner_label":"16vcpu-runner","sku":"linux_16_core"}`.
The catalog supplies the list price; estimates exclude account discounts.

Non-pytest adopters can use `resolve-incremental-pr-base` with
`validation-evidence: 'true'` and `evidence-step-name` to require a successful
completion marker in the named evidence job. Place that marker after every
required check and execution-inventory validation. A newer failed, cancelled,
timed-out or unverifiable validation retains the fallback base. This mode does
not use the ancestry index-lag fallback, which could miss newer failed proof.
When `reused` is false, callers requiring a validated baseline must run a full
checkpoint. Follow the [tested-tree policy and setup](test-selection-policy.md#which-git-identity-was-actually-tested)
for PR-head versus synthetic-merge comparisons, parent validation and main reverts.
Keep explicit full checkpoints and invalidate completion markers when the execution
contract changes.
