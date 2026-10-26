# Improve one CI cost first

See the [selection and evidence policy](test-selection-policy.md) for the scenario map, tested Git identities, reruns and Python/JavaScript setup.

For a staged rollout across the toolkit, use the
[adoption checklist](tutorials/adoption-checklist.md).

Start with a report if you do not know the bottleneck. If repeated dependency
installation is already the problem, replace those setup steps directly. Use
[the public action version policy](actions.md#availability-and-pinning): the
root/short paths below use `@v1` for automatic compatible 1.x upgrades.
Use an exact release tag or commit SHA if your project requires fixed revisions.

## Report a completed workflow

Save this as `.github/workflows/observe-ci.yml`. Change `CI` to the name of your
validation workflow and `Validation gate` to its exact required job name. Commit
the observer to your default branch; it starts observing subsequent runs.

```yaml
name: CI report
on:
  workflow_run:
    workflows: [CI]
    types: [completed]
permissions:
  contents: read
  actions: read
  checks: read
  pull-requests: write
jobs:
  report:
    runs-on: ubuntu-latest
    steps:
      - uses: gigaverse-app/ci-esta/actions/ci-observability@v1
        with:
          github-token: ${{ github.token }}
          run-id: ${{ github.event.workflow_run.id }}
          run-attempt: ${{ github.event.workflow_run.run_attempt }}
          commit-sha: ${{ github.event.workflow_run.head_sha }}
          pull-request-number: ${{ format('{0}', github.event.workflow_run.pull_requests[0].number || '') }}
          required-gates-json: '[{"kind":"actions_job","job_name":"Validation gate"}]'
          analyze-critical-path: 'true'
          post-sticky: 'true'
      - uses: actions/upload-artifact@v7
        if: always()
        with:
          name: ci-report-${{ github.event.workflow_run.id }}-${{ github.event.workflow_run.run_attempt }}
          path: |
            ci-observability.json
            ci-observability.md
            ci-observability.prom
          if-no-files-found: error
```

There is no source checkout or application install in this observer. The action
installs its isolated reporter and reads the completed run as data. Keep the
observer outside your validation gate's dependencies. For summary-only reporting,
set `post-sticky: 'false'` and reduce `pull-requests` to `read`. Fork runs may not
provide a PR number; the summary and artifacts remain available.

Open the report on the next completed PR run. Check the named gate, source SHA,
collection status and slowest steps. Missing rate information leaves exact cost
unavailable. [Report fields and optional reusable workflow](github-actions-observability.md).

## Cache your Python environment

In your existing job, keep checkout, services and test arguments. Replace its
Python setup, uv setup and dependency installation with the middle step:

```yaml
name: Tests
on:
  pull_request:
  push:
    branches: [main]
jobs:
  tests:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v7
      - uses: gigaverse-app/ci-esta/actions/setup-cached-uv@v1
        with:
          python-version: '3.12'
          sync-args: '--group test'
      - run: uv run --no-sync pytest
```

Use your Python version and actual dependency groups; omit `sync-args` if defaults
are right. The action always runs `uv sync --locked`, including after a cache hit.
It repairs unusable environments. Keep extra system-library/ABI inputs in
`cache-variant`. Compare cold and warm setup; if restoring the expanded environment
costs more than installing it, set `cache-environment: 'false'` and retain uv's
package cache. [Cache identity and recovery](environment-cache.md).

## Choose the next improvement from the report

- Unaffected tests start services: [select complete lanes](https://github.com/gigaverse-app/pytest-selective/blob/main/docs/ci.md#select-whole-ci-lanes).
- Identical declared work already passed: [reuse completion evidence](evidence-reuse.md), including independently passing jobs from partly failed workflows.
- One shard dominates: [copy the complete shard example](../examples/pytest-shards/README.md). Choose runner capacity separately from process count.
- Selection keeps growing: [audit dependencies and protect fixture scope](https://github.com/gigaverse-app/pytest-selective/blob/main/docs/selection-health.md).
- Tests hang or leave CPUs idle: [enable focused diagnostics](runners-and-diagnostics.md#resource-and-pytest-diagnostics).

Keep full checkpoints and required completion/coverage checks. Compare source
revisions, test identities and outcomes alongside elapsed time and summed runner
usage. The [optimization guide](ci-optimization.md) explains the combined workflow.
