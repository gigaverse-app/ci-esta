# Measure GitHub Actions latency and runner cost

CI-esta reads GitHub's run and job APIs and writes one versioned JSON report, a human-readable Markdown summary and bounded Prometheus metrics. No hosted CI-esta service is required.

## Add a reporting job

For CI that already has a long critical path, prefer a separate completed-run
observer. CI-esta uses this arrangement itself: reporting reads a finished run
and cannot delay or decide its validation result. One reusable workflow owns
the report installation and artifact publication; consumers only declare their
source workflows and exact gate names.

```yaml
name: CI observability
on:
  workflow_run:
    workflows: [CI]
    types: [completed]
permissions:
  contents: read
  actions: read
  checks: read
  pull-requests: read
jobs:
  report:
    uses: gigaverse-app/ci-esta/.github/workflows/report.yml@<reviewed-commit>
    with:
      run-id: ${{ github.event.workflow_run.id }}
      run-attempt: ${{ github.event.workflow_run.run_attempt }}
      head-sha: ${{ github.event.workflow_run.head_sha }}
      required-gates-json: '[{"kind":"actions_job","job_name":"Validation gate"}]'
```

The observer must land on the default branch before `workflow_run` triggers it.
It observes success, failure and cancellation. It has read-only permissions,
never checks out the observed commit, disables source artifact downloads and PR
comments, and uses the existing reporter pinned to an immutable revision. This
also allows observation of fork PRs without executing their code. The resulting
workflow summary and `ci-esta-<run-id>-<attempt>` artifact contain Markdown,
versioned JSON and Prometheus metrics. Inspect `collection_status` before using
partial or unavailable measurements. An empty gate list leaves gate latency
unassessed while still reporting jobs, steps and runner time.

For a report inside the original workflow instead:

Run this after your existing aggregate gate. Replace `Validation gate` with its exact display name. Pin the action to a reviewed commit SHA for production.

```yaml
report:
  needs: gate
  if: ${{ always() }}
  permissions:
    contents: read
    actions: read
  runs-on: ubuntu-latest
  steps:
    - uses: gigaverse-app/ci-esta/.github/actions/ci-observability@main
      with:
        github-token: ${{ github.token }}
        required-gates-json: '[{"kind":"actions_job","job_name":"Validation gate"}]'
        post-sticky: 'false'
        test-selection-artifact: ''
        full-suite-reference-artifact: ''
```

The action installs its Python reporter in an isolated temporary environment. It does not need your application's Python environment or a repository checkout. Composite actions require Bash; the reporting action is validated on Linux runners. The CLI is tested on Python 3.11 and 3.14; local Windows tests are part of the extraction checks.

An Actions gate selector must provide exactly one of `job_name` (the job's display name, recommended) or legacy `runner_name` (the machine identity from GitHub's API). They are different fields. Duplicate matches leave the gate unobserved rather than choosing an arbitrary job.

Outputs `report-file`, `markdown-file` and `prometheus-file` identify the generated files. Archive them using `actions/upload-artifact`. Reporting steps are best effort; a telemetry outage must not decide whether application validation passes.

To post a sticky PR report, supply `pull-request-number`, set `post-sticky: 'true'`, and grant `pull-requests: write` only in a trusted context. The local CLI never posts comments.

## What the numbers mean

| Measurement | Meaning and limit |
| --- | --- |
| Required-gate elapsed time | Time from workflow creation to explicitly configured gates; no inferred full DAG |
| Job admission delay | Time before a job starts, which can include dependencies, approvals and runner queueing |
| Runner seconds | Observed timed jobs across attempts, including retries |
| Rounded runner minutes | Sum of per-job ceiling-rounded durations; an estimate, not a GitHub invoice |
| Dollar estimate | Configured runner-label/SKU rates multiplied by rounded minutes; withheld when any timed job is unpriced |
| Overlapping prior runs | Observed cost of prior PR runs that overlap the current run |
| Test-selection savings | Optional comparison with comparable full-suite timing references; not a guaranteed counterfactual |

Use `runner-sku-rates-json` only with rates you maintain. GitHub plans, included usage, discounts and billing policies are outside this report. Missing gate configuration or API data produces a partial/unavailable report rather than invented precision. Exact run IDs and SHAs belong in the JSON report, not Prometheus grouping labels.

## Local reports and offline rendering

```bash
pip install 'git+https://github.com/gigaverse-app/ci-esta.git'
# Set GITHUB_TOKEN or GH_TOKEN in your environment; do not put it in command history.
ci-esta report --repository owner/repo --run-id 123456 --gate 'Validation gate'
ci-esta render ci-esta-report/ci-observability.json \
  --markdown report.md --prometheus report.prom
```

The alpha distribution installs pytest-selective's shared explanation contract from an immutable Git revision. Neither package is claimed to be published on PyPI. The Actions for evidence, gates and change collection do not require a Python application or pytest.

## Prometheus without unbounded labels

`publish-prometheus-snapshot` replaces one stable Pushgateway group using HTTP PUT. It includes repository identity and allows additional bounded labels such as environment or service. Never group by run ID, commit SHA or branch. `failure-mode: warn` is the default; use `fail` only when publication itself is required.

The reporter supports a repository-neutral extension:

```json
{"pytest":{"shard_count":4,"wall_seconds":78,"total_test_seconds":293}}
```

Pass that JSON through `extensions-file`. Existing `backend` and `ai` enrichment profiles remain compatibility adapters for the source consumers, not requirements for new adopters. See [project integrations](integrations.md) for the selection explanation contract.
