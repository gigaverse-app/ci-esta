# Measure one workflow, then change admission

For a first read-only measurement, install the released CI-esta package
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

Copy the [complete public-action observer](https://github.com/gigaverse-app/ci-esta/blob/main/docs/quickstart.md#report-a-completed-workflow).
Adapt the source workflow name and exact required job names. The `actions/ci-observability` action uses
`run-id`, `run-attempt` and `commit-sha` from the completed source run. Check
[entry-point availability](https://github.com/gigaverse-app/ci-esta/blob/main/docs/actions.md)
before selecting a release pin. The optional reusable workflow remains documented
in the [reporting guide](https://github.com/gigaverse-app/ci-esta/blob/main/docs/github-actions-observability.md).

For read-only reporting set `post-sticky: 'false'` and `pull-requests: read`.
Enable comments only when authorized. The observer must exist on the default
branch to observe future runs. Do not check out or execute source PR code in it.
Basic reporting neither needs an MCP server nor changes the application's Python
dependencies.

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
