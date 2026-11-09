# Pack short matrix jobs onto fewer runners

Use this when a report shows many short matrix jobs, typically one per Python
version or tox/nox environment, where each job's setup (checkout, interpreters,
dependency installation) costs about as much as its tests. Every job pays that
setup again. Running several matrix entries on one runner pays it once per runner.

In the [structlog trial](https://github.com/gigaverse-app/structlog-ci-esta/pull/1),
six one-version jobs became three two-version runners: summed runner time fell
23% (median 250 s to 192 s) with the same 18 tox environments and test counts,
and the time to the required check stayed inside `main`'s own range. One runner
for all six versions used even less runner time but made the required check
about 25 s slower, because that job is on the critical path. Measure your layouts;
do not copy the ratio.

Do not use it when tests dominate each job (balance test files with
[timing-based shards](learned-test-timings.md) instead), or when one packed job
would lengthen the critical path more than your team accepts.

## Plan which entries share a runner

`plan-runner-pools` assigns every entry to exactly one runner. Its `pools` output
is a JSON list of `{id, shard_count, first_shard, last_shard}`; attach your entries
by slicing them with those 1-based ranges.

```yaml
name: CI
on:
  pull_request:
  push:
    branches: [main]
  workflow_dispatch:
    inputs:
      entries-per-runner:
        description: Matrix entries on each runner. 1 reproduces one job per entry.
        type: choice
        options: ['1', '2', '3', '6']
        default: '2'
permissions:
  contents: read
env:
  PYTHON_VERSIONS: '["3.10", "3.11", "3.12", "3.13", "3.14", "3.15"]'
jobs:
  plan:
    runs-on: ubuntu-latest
    outputs:
      pools: ${{ steps.matrix.outputs.pools }}
    steps:
      - id: count
        run: echo "count=$(jq length <<< "$PYTHON_VERSIONS")" >> "$GITHUB_OUTPUT"
      - uses: gigaverse-app/ci-esta/actions/plan-runner-pools@v1
        id: pools
        with:
          shards: ${{ steps.count.outputs.count }}
          shards-per-runner: ${{ inputs.entries-per-runner || '2' }}
      - id: matrix
        env:
          POOLS: ${{ steps.pools.outputs.pools }}
        run: >
          echo "pools=$(jq -c --argjson v "$PYTHON_VERSIONS"
          'map(. + {versions: $v[.first_shard - 1:.last_shard]})' <<< "$POOLS")"
          >> "$GITHUB_OUTPUT"
  tests:
    name: Tests on ${{ join(matrix.pool.versions, ', ') }}
    needs: plan
    runs-on: ubuntu-latest
    strategy:
      fail-fast: false
      matrix:
        pool: ${{ fromJSON(needs.plan.outputs.pools) }}
    steps:
      - uses: actions/checkout@v7
      - id: versions
        env:
          VERSIONS: ${{ toJSON(matrix.pool.versions) }}
        run: |
          {
            echo 'list<<EOF'
            jq -r '.[]' <<< "$VERSIONS"
            echo 'EOF'
          } >> "$GITHUB_OUTPUT"
      - uses: actions/setup-python@v7
        with:
          python-version: ${{ steps.versions.outputs.list }}
          allow-prereleases: true
      - uses: astral-sh/setup-uv@v10.3.3
      - name: Run this runner's entries
        env:
          VERSIONS: ${{ toJSON(matrix.pool.versions) }}
          POOL: ${{ matrix.pool.id }}
        run: |
          factors=()
          for version in $(jq -r '.[]' <<< "$VERSIONS"); do factors+=(-f "$version"); done
          uvx --with tox-uv tox run-parallel --parallel auto --parallel-no-spinner \
            --result-json "tox-results-$POOL.json" "${factors[@]}"
      - uses: actions/upload-artifact@v7
        if: ${{ !cancelled() }}
        with:
          name: tox-results-${{ matrix.pool.id }}
          path: tox-results-*.json
          if-no-files-found: error
```

Keep your repository's own setup steps (for example an existing cached-uv
action) and its action pinning policy. If the entries come from another job,
such as trove classifiers, read them from that job's output instead of `env`.

### Entries on more than one operating system

Every runner of a packed job uses the job's one `runs-on`, so pack only entries
that run on the same image. With Linux, macOS and Windows entries, plan one set
of pools per operating system: one `plan-runner-pools` step, one output and one
packed job each. An entry that needs a different image from its neighbours, such
as an old Python version that only `ubuntu-24.04` still provides, stays out of
the pools as its own job, for example a `matrix.include` entry with its own
`runs-on`. Put every packed and unpacked test job in the required aggregate
job's `needs`.

## Run several entries in one job

The job must fail when any entry fails. Never append `|| true`.

**tox.** Run `tox list` first and select the environments by the names your
`tox.ini` or `pyproject.toml` defines. The example's environments are composed
from factors (`3.10-tests`, `3.10-docs`), and repeated `-f` selects the union of
factors, so `-f 3.10 -f 3.11` runs every `3.10-*` and `3.11-*` environment. A
factor must be a whole dash-separated part of the name: `-f 3.10` does not match
`py3.10`. For environments named `py3.10`, `py3.11`, pass them with `-e`:

```bash
envs=$(jq -r 'map("py" + .) | join(",")' <<< "$VERSIONS")
uvx --with tox-uv tox run-parallel --parallel auto --parallel-no-spinner \
  --result-json "tox-results-$POOL.json" -e "$envs"
```

`tox run-parallel` runs them concurrently and exits non-zero if any fails;
`--result-json` records the environments that ran, for the inventory comparison.

**nox.** `--python` takes several interpreters; sessions run one after another
and nox exits non-zero if any fails:

```bash
nox --session tests --python 3.10 3.11
```

**uv and pytest.** Give each interpreter its own project environment, or the
concurrent runs overwrite one `.venv`:

```bash
pids=()
for version in $(jq -r '.[]' <<< "$VERSIONS"); do
  UV_PROJECT_ENVIRONMENT=".venv-$version" uv run --locked --python "$version" \
    pytest -q --junitxml="junit-$version.xml" > "pytest-$version.log" 2>&1 &
  pids+=("$!")
done
status=0
for pid in "${pids[@]}"; do wait "$pid" || status=1; done
cat pytest-*.log
exit "$status"
```

Running the entries one after another also works and still pays setup once; use
concurrency only when the runner has spare cores (standard Linux runners have 4).

## Keep the gate honest

- Put the packed test job **directly** in the required aggregate job's `needs`.
  A gate that reaches tests only through a job with `if: always()` (a coverage
  combiner, for example) can stay green when a test job fails.
  `ci-esta adoption --root .` flags that shape as `gate-indirect`.
- Prove it: on a throwaway branch, add a test that fails on one entry only, and
  check that the required check fails. Delete the branch afterwards.
- Compare the inventory: the set of tox environments, nox sessions or JUnit
  test counts must match the old layout entry by entry.
- These commands do not install CI-esta into the test environment, so they work
  for projects testing Python versions older than CI-esta's own 3.11 floor.
  `plan-runner-pools` installs its own runtime.

## Measure on the same head

The workflow file is the change, so the old layout cannot run on the new commit.
The `entries-per-runner` input is the same-head control: dispatch the new
workflow with `1` (the old job graph) and with each candidate, plus recent `main`
runs of the unchanged workflow. `1` reproduces the old jobs, not the old steps:
those runs also pay for the `plan` job, the gate if you added one, and new steps
such as `--result-json` and the artifact upload. Credit packing only with the
change from `1` to each candidate on the same head, and attribute the change from
the unchanged workflow to `1` to those added jobs and steps. Dispatch one run at a time: dispatched runs on one branch share
the workflow's concurrency group, and `cancel-in-progress` cancels the earlier
run. Then report each run:

```bash
ci-esta report --repository OWNER/REPO --run-id RUN_ID --gate 'Your required check' \
  --critical-path --output-dir report-RUN_ID
```

Compare `required_gates[].elapsed_from_creation_seconds` (time to the required
check), `runner_cost.raw_runner_seconds` (summed job time) and the job count.
See the [report field reference](github-actions-observability.md#report-json-fields).
