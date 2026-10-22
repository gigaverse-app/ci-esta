# Measure one workflow, then change admission

For a first read-only measurement, install CI-esta from a reviewed Git revision
in a separate tool environment (Python 3.11+). Use a token already authorized for
the target repository in `GH_TOKEN` or `GITHUB_TOKEN`; the report command accepts
no token argument and posts no comment.

```bash
ci-esta report --repository OWNER/REPO --run-id RUN_ID --run-attempt 1 \
  --commit-sha SOURCE_HEAD_SHA --gate 'Validation gate' --critical-path \
  --output-dir ci-esta-report
```

Substitute the observed run ID, attempt, source SHA and exact required job name.
Repeat `--gate` for multiple jobs. Omit it if no gate is known, and describe gate
latency as unassessed. Inspect collection errors and missing timestamps before
using the report as evidence. The output is JSON, Markdown and Prometheus.

## Add ongoing reporting

Use the [README observer example](https://github.com/gigaverse-app/ci-esta#start-by-measuring-one-workflow)
or [complete workflow](https://github.com/gigaverse-app/ci-esta/blob/main/.github/workflows/observe-ci.yml).
Adapt the source workflow name and required jobs to the target. The reusable
workflow's verified interface is:

```yaml
jobs:
  report:
    uses: gigaverse-app/ci-esta/.github/workflows/report.yml@e9d279269e80a4e68435dbd65cdb9dbd23048f7b
    with:
      run-id: ${{ github.event.workflow_run.id }}
      run-attempt: ${{ github.event.workflow_run.run_attempt }}
      head-sha: ${{ github.event.workflow_run.head_sha }}
      required-gates-json: '[{"kind":"actions_job","job_name":"Validation gate"}]'
      analyze-critical-path: true
```

This is a fragment for a `workflow_run` observer with `types: [completed]` and
read-only `contents`, `actions`, `checks`, `pull-requests` permissions. It must
exist on the default branch to observe future runs. Keep the trusted reusable
reporter; do not check out or execute source PR code in this observer. Review the
pin against the target's requirements. Basic reporting neither needs an MCP
server nor changes the application's Python dependencies.

## Read the result

Start with the longest job and its slowest steps. Compare required-gate elapsed
time with summed job time: parallel jobs make these different. Admission delay
does not establish its cause. Rerun/cancelled-work cost matters to iteration
efficiency even when successful-pair benchmarks exclude it.

For Python tests, hand the input model to
[pytest-selective's skill](https://github.com/gigaverse-app/pytest-selective/blob/main/skills/pytest-selective/SKILL.md).
Keep docs/package checks and required statuses when runtime lanes are skipped.
For whole-lane reuse, follow the
[full admission/receipt/gate example](https://github.com/gigaverse-app/ci-esta/blob/main/.github/workflows/ci.yml)
and [policy guide](https://github.com/gigaverse-app/ci-esta/blob/main/docs/evidence-reuse.md);
do not copy just the skip condition without its receipt and failure handling.

The report can be rendered offline later:

```bash
ci-esta render ci-esta-report/ci-observability.json \
  --markdown report.md --prometheus report.prom
```

The [published example](https://github.com/gigaverse-app/ci-esta/blob/main/docs/benchmarks/2026-10-22.md)
shows source identities, limits and separate observer overhead. Use it as an
evidence format, not an expected saving for a new project.

For cache identity, learned timing feedback and parallelism, follow the
[optimization guide](https://github.com/gigaverse-app/ci-esta/blob/main/docs/ci-optimization.md).
The Gantt shows observed intervals and highlights the computed dependency chain
when complete topology is available. Inspect execution CPM, per-job slack and
delay separately; delay is not pure queue time. Unknown topology remains
unavailable. When auditing upstreaming, distinguish shipped, configured and
live-verified states; the
[closure ledger](https://github.com/gigaverse-app/ci-esta/blob/main/docs/upstream-closure.md)
links implementations, caller PRs and live evidence.
