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
  pull-requests: write # Only to post the sticky; use read to keep the report in the job summary.
jobs:
  report:
    uses: gigaverse-app/ci-esta/.github/workflows/report.yml@<reviewed-commit>
    with:
      run-id: ${{ github.event.workflow_run.id }}
      run-attempt: ${{ github.event.workflow_run.run_attempt }}
      head-sha: ${{ github.event.workflow_run.head_sha }}
      required-gates-json: '[{"kind":"actions_job","job_name":"Validation gate"}]'
      pull-request-number: ${{ format('{0}', github.event.workflow_run.pull_requests[0].number || '') }}
      post-sticky: true
      # When `workflows:` lists several workflows, give each its own sticky:
      # sticky-key: ${{ github.event.workflow_run.name }}
```

The observer must land on the default branch before `workflow_run` triggers it.
It observes success, failure and cancellation. The reusable workflow checks out
CI-esta at its own commit (`job.workflow_sha`), so one pin covers the workflow
and the reporter; it never checks out the observed commit or executes its code,
which also makes fork PRs safe to observe. Artifacts uploaded by a fork's run
are ignored, and every path or name taken from a run is escaped before it is
rendered. The resulting workflow summary and `ci-esta-<run-id>-<attempt>`
artifact contain Markdown, versioned JSON and Prometheus metrics. Inspect
`collection_status` before using partial or unavailable measurements. An empty
gate list leaves gate latency unassessed while still reporting jobs, steps and
runner time.

The reusable workflow declares no permissions of its own: the caller's grant is
the ceiling. Grant `pull-requests: write` only when `post-sticky` is true.

Lane plans use `lane-selection-artifact: test-lane-selection` by default. For
file selection, explicitly pass `test-selection-artifact: test-impact-explanation`
and, if produced by your full runs, `full-suite-reference-artifact: ci-full-suite-reference-v1`.
These two inputs default to empty to preserve existing callers. The current
reporter loads file explanations only with `post-sticky: true`; a missing
reference leaves savings unmeasured. This configures observation, not test execution.

### What the sticky shows

Add [measured-impact pairs](measured-impact.md) to preserve verified optimization
results at the top of the sticky. Bun execution artifacts show structured counts,
wall time and fallback reasons without installing pytest-selective. Timeline and
critical-path diagnostics are always collapsed, including reports with no tests.

```text
[CI-esta banner: dark or light, following the reader's GitHub theme]
[merge-ready 2m 9s] [lanes 1 of 14 ran] [skipped ≈28 runner-min] [runner 4 min] [cost $0.03]  CI · `17f3325`

🎯 Test selection · by pytest-selective   (when the run uploaded a file-selection explanation)
🧪 Test lanes · by pytest-selective       (when the run uploaded a lane plan; one square per lane)
⏱️ CI time and cost                        (collapsed beside a selection section)
   closed Timeline and critical path: one row per job labeled with its run and ⏳ wait, orange
   for the critical path, a green bar from merge-ready on
[mark] Powered by CI-esta · run · schema
```

The badge line answers "can I merge, what ran, what did it cost" before any
detail, colored with GitHub's status palette; each badge's alt text carries its
figure. Readiness appears only when required gates are configured. GitHub's API
has no `needs` graph, so the gantt infers the chain: GitHub creates a job when
the jobs it needs finish, so a job's predecessor is the one that finished just
before it was created. A pull request keeps one sticky per `sticky-key`; each
new run updates it in place, and an older run never overwrites a newer one.

The banner and mark live in [`docs/assets`](assets/). Change both banners
through [`scripts/render_sticky_banners.py`](../scripts/render_sticky_banners.py)
rather than editing one theme by hand.

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
| Slowest step per job | Latest-attempt API step durations, with links to job logs; all steps remain in the JSON report |
| Rounded runner minutes | Sum of per-job ceiling-rounded durations; an estimate, not a GitHub invoice |
| Dollar estimate | Configured runner-label/SKU rates multiplied by rounded minutes; withheld when any timed job is unpriced |
| Overlapping prior runs | Observed cost of prior PR runs that overlap the current run |
| Test-selection savings | Optional comparison with comparable full-suite timing references; not a guaranteed counterfactual |

Use `runner-sku-rates-json` only with rates you maintain. GitHub plans, included usage, discounts and billing policies are outside this report. Missing gate configuration or API data produces a partial/unavailable report rather than invented precision. Exact run IDs and SHAs belong in the JSON report, not Prometheus grouping labels.

Step timing distinguishes completed, accrued and unavailable measurements. Missing,
skipped or reversed timestamps stay unavailable; a completed step with identical
timestamps is a measured zero at GitHub's timestamp precision. Steps explain job
time and are never added to runner usage. Older v1 reports without steps still load.

## Local reports and offline rendering

```bash
pip install "ci-esta>=0.1.0,<0.2.0"
# Set GITHUB_TOKEN or GH_TOKEN in your environment; do not put it in command history.
ci-esta report --repository owner/repo --run-id 123456 --gate 'Validation gate'
ci-esta render ci-esta-report/ci-observability.json \
  --markdown report.md --prometheus report.prom
```

The Python distribution installs pytest-selective's shared explanation contract through a compatible package-version range. The Actions for evidence, gates and change collection do not require a Python application or pytest.

## Prometheus without unbounded labels

`publish-prometheus-snapshot` replaces one stable Pushgateway group using HTTP PUT. It includes repository identity and allows additional bounded labels such as environment or service. Never group by run ID, commit SHA or branch. `failure-mode: warn` is the default; use `fail` only when publication itself is required.

The reporter supports a repository-neutral extension:

```json
{"pytest":{"shard_count":4,"wall_seconds":78,"total_test_seconds":293}}
```

Pass that JSON through `extensions-file`. Existing `backend` and `ai` enrichment profiles remain compatibility adapters for the source consumers, not requirements for new adopters. See [project integrations](integrations.md) for the selection explanation contract.
