# Measure GitHub Actions latency and runner cost

CI-esta reads GitHub's run and job APIs and writes one versioned JSON report, a human-readable Markdown summary and bounded Prometheus metrics. No hosted CI-esta service is required.

Start with the [public-action quickstart](quickstart.md#report-a-completed-workflow).
The reusable-workflow alternative below additionally owns artifact upload.

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
    uses: gigaverse-app/ci-esta/.github/workflows/report.yml@v1
    with:
      run-id: ${{ github.event.workflow_run.id }}
      run-attempt: ${{ github.event.workflow_run.run_attempt }}
      head-sha: ${{ github.event.workflow_run.head_sha }}
      required-gates-json: '[{"kind":"actions_job","job_name":"Validation gate"}]'
      pull-request-number: ${{ format('{0}', github.event.workflow_run.pull_requests[0].number || '') }}
      post-sticky: true
      sticky-workflow: CI
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

GitHub's generic jobs listing can briefly lag a completed workflow. When its
run metadata is terminal but jobs still appear active, the reporter refreshes
once through the exact-attempt endpoint. Terminal evidence for the same job
and attempt also replaces stale accrued entries in the billing view. If the
refresh fails or remains inconsistent, the report keeps the available evidence
and marks collection partial; it never infers a job's success from run success.
Live workflows keep their ordinary snapshot without this extra request.

The reusable workflow declares no permissions of its own: the caller's grant is
the ceiling. Grant `pull-requests: write` only when `post-sticky` is true.

Lane plans use `lane-selection-artifact: test-lane-selection` by default. For
file selection, explicitly pass `test-selection-artifact: test-impact-explanation`
and, if produced by your full runs, `full-suite-reference-artifact: ci-full-suite-reference-v1`.
These two inputs default to empty to preserve existing callers. The current
reporter loads file explanations only with `post-sticky: true`; a missing
reference leaves savings unmeasured. This configures observation, not test execution.

`actions/test-impact@v1` defaults to the selector's reason-bearing explanation format;
override `explanation-format: '1'` when sending its artifact to a legacy reader.
The sticky shows the recorded selection reason beside its file counters and inside
the collapsed details. An older full-suite artifact without a reason explicitly
says its trigger was not recorded. The reporter never infers a trigger from the
current run attempt or labels. Direct pytest-selective action users can request
`explanation-format: '2'` after upgrading their report reader; its default format
remains compatible with older strict readers.

### What the sticky shows

Add [measured-impact pairs](measured-impact.md) to preserve verified optimization
results inside CI time and cost. Bun execution artifacts show structured counts,
wall time and fallback reasons without installing pytest-selective. Timeline and
critical-path diagnostics are always collapsed, including reports with no tests.

```text
[CI-esta banner: dark or light, following the reader's GitHub theme]
[merge-ready 2m 9s] [selected 93 / 1,293 files] [reused 2 lanes] [runner 17 min]
[Required checks passed] CI · `17f3325` · attempt 1 · complete snapshot
--------------------------------------------------------------------
> Test selection
  93 / 1,293 files selected
  Plan before evidence reuse
--------------------------------------------------------------------
> What else avoided work?
  2 proven lanes reused · about 1m 33s runner time avoided (estimated)
  Environment cache hits and verified image reuse, when measured
--------------------------------------------------------------------
> Sharding & runner efficiency
  Measured shards / pools · visible CPUs per pool
  Observed pool wall time · slot occupancy
--------------------------------------------------------------------
> CI time and cost
  merge-ready in 2m 9s · 17 rounded runner-min
   closed Timeline and critical path: one row per job labeled with its run and ⏳ wait, orange
   for the critical path, a green bar from merge-ready on
--------------------------------------------------------------------
Savings across selection, reuse, and caching are not additive.
[mark] CI-esta · Let proven work rest. Measure the rest.
Reading this report · run · schema
```

The example above is illustrative. The badge line answers "can I merge, what was selected,
what evidence was reused, what did it cost" before any
detail, colored with GitHub's status palette; each badge's alt text carries its
figure. Each closed section keeps a bold title and separate metric lines visible;
opening it reveals the existing explanations and diagnostic tables. The status
pill describes observed required gates, independently of snapshot completeness:
a complete snapshot can still contain failed or running checks. Missing gates
never earn a passed status. Readiness appears only when required gates are configured.
Enable `analyze-critical-path` to read the source workflow topology at its
verified revision and compute dependency paths and execution slack. Timing
adjacency alone is not a dependency edge; unsupported topology stays unavailable. A pull request keeps one sticky per `sticky-key`; each
new run updates it in place. The publisher compares source run, attempt, completed
gates and observation time before replacing a report.

### Shared headlines and publication ownership

Python and Bun use the same headline fields, in the same order: readiness,
selected, executed, reused, runner minutes, and estimated cost. Both lead with
the same **Selection and execution** section; provider-specific explanations
stay inside it. Missing evidence is never converted to zero. Uninstrumented
sharding sections are omitted, with collection instructions in the avoided-work
section; missing headline evidence remains explicit.

Python's `selected` count describes the plan before evidence reuse, not the
files that actually ran. Bun's full/none modes establish selected-file counts
(all files for full, always-run contracts for none);
native scoped selection does not expose a separate plan inventory and remains
unavailable. `executed` uses the observed file inventory when supplied, then
measured shard processes, then started GitHub jobs in the current attempt.
The unit is always shown. Jobs include setup, checks and reporting; neither
job nor shard counts establish a test count or passing tests. A failed
full run can select every file while executing only some. A reused plan without
an execution inventory does not invent one. Multiple work inventories are not
summed because they can overlap. Reuse retains its evidence's units (lanes or
work units), never file counts inferred from skipped jobs. None of these counts
implies time saved or passing checks.

The reusable workflow forwards `runner-sku-rates-json` to the same accounting
code as direct action callers. CI-esta owns the standard and larger-runner price
catalog, keyed by GitHub billing SKU. Map organization runner names to those SKUs:

```yaml
runner-sku-rates-json: >-
  [
    {"sku":"linux_8_core","runner_label":"8vcpu-runner"},
    {"sku":"linux_16_core","runner_label":"16vcpu-runner"}
  ]
```

Omitting `usd_per_minute` uses the built-in
[GitHub list rates](https://docs.github.com/en/billing/reference/actions-runner-pricing)
(verified 2026-10-24). Recognized single-label standard runners are priced without
configuration; known public repositories use their free standard-runner rate.
When visibility is absent, the rate is explicitly a list-price estimate.
The catalog covers standard runners and GitHub's published x64, arm64, macOS and
GPU larger-runner SKUs. Official larger macOS labels also resolve automatically.
Larger runners remain billable in public repositories. Organization runner names
need an explicit label-to-SKU mapping; their names are never parsed to guess hardware.
Multiple labels may map to one SKU.

For negotiated prices, self-hosted hardware or a SKU outside the catalog, supply
`usd_per_minute` as an escape hatch. It overrides the catalog and public free rate,
including when explicitly set to zero:

```yaml
runner-sku-rates-json: '[{"sku":"private_pool","runner_label":"build-pool","usd_per_minute":"0.015"}]'
```

Unknown SKUs without an explicit price leave that usage unpriced and withhold the
total; the report still shows known prices. Catalog-derived SKU names include
their verification date in the output for provenance. Existing configurations
with explicit prices remain supported. Deploy the CI-esta release containing
catalog mappings before adopting mappings without prices in consumers of `@v1`.
Maintain those overrides for your account. Cost is a per-job rounded-minute
estimate before allowances and discounts, not an invoice. Automatic SKU names
record the source: `github_20261024_*` for list rates and `github_public_*` for
free public standard runners. The existing JSON shape remains compatible with
older v1 readers. Unmatched timed jobs withhold the total, while the known subtotal
breakdown and count of unpriced runner minutes remain visible.

Set `sticky-workflow` to the exact source workflow name that owns the PR comment.
Other observed workflows still produce summaries and artifacts. Keep `sticky-key`
stable across upgrades: distinct keys deliberately create distinct comments, and
sharing a key does not combine unrelated reports.

The reusable workflow serializes report jobs per PR without cancelling an active
publisher. Consumers do not need to copy its concurrency block. Direct action
callers use the same publication code; they should serialize overlapping jobs
if they need strict ordering, since GitHub's comment API has no atomic upsert.
The publisher also repairs matching owned duplicates, including a concurrent first
create: it keeps the oldest permalink, saves the newest snapshot there, then
removes redundant comments from the same bot or authenticated user. Other people's comments, other keys and
malformed duplicate snapshots are preserved. A failed save never deletes the
other report. This recovery is not a cross-workflow lock.

Install these inputs only after the release containing them is available at
`@v1`. Automatic `workflow_run` observers load their definition from the default
branch; changing a PR branch does not update that observer until merge.

The banner and mark live in [`docs/assets`](assets/). Change both banners
through [`scripts/render_sticky_banners.py`](../scripts/render_sticky_banners.py)
rather than editing one theme by hand.

### Execution measurements

CI-esta discovers `ci-esta-reuse-*`, `ci-esta-shards-*`, `ci-esta-cache-*` and
`ci-esta-image-*` artifacts in the observed
run. Each contains one versioned JSON record bound to its run ID, attempt and head
SHA. Old-attempt and fork artifacts cannot explain the current attempt. Measurement
errors stay visible in `measurement_errors` without removing the timing report.

`resolve-lane-evidence` publishes the successful source job IDs and input receipt
it actually admitted. The reporter counts only lanes whose current jobs were
skipped and re-reads the source jobs' GitHub timestamps. Their durations estimate
runner work avoided; they do not measure wall-clock savings or billed minutes.
The same proof job is never added twice. Selection and evidence reuse can overlap,
so their historical estimates must not be added together.

`setup-cached-uv` records hit, miss, repaired, disabled or unavailable only after locked
synchronization succeeds. These counts describe complete environments, separately
from uv's download cache. `reuse-ecr-image` records successful digest-preserving
promotions. Neither a cache hit nor an image promotion establishes seconds saved
without a comparable cold run or build. Existing Docker cache signals are retained
in the same avoided-work section.

Artifacts are used because GitHub's jobs API omits the inner steps of composite
actions. Cache measurement includes the duration of environment validation and
locked sync; disabled and unavailable restores do not count as cache misses.
Disabled caches are shown as disabled, and an absent cache record as not recorded.

`ci-esta-pytest run-local` now writes `ci-esta-shards.json` in its log directory
after all children exit, including on test failure. Publish it from each pool:

```yaml
- name: Publish shard execution intervals
  if: always()
  uses: gigaverse-app/ci-esta/actions/publish-shard-measurements@<reviewed-commit>
  with:
    path: pytest-logs/ci-esta-shards.json
    pool: ${{ matrix.first }}-${{ matrix.last }}
```

Use the actual `--log-dir` and the pool keys from your matrix. Slot occupancy is
the sum of observed child-process durations divided by allocated slots times
pool wall time. It includes Python startup and subprocess waits. It is not CPU
utilization. Global occupancy is withheld when pools overlap or any configured
shards are missing. Per-pool wall, visible logical CPUs, idle slot-time, tail/median,
exit codes and all intervals remain available. Quota, throttling and duration
prediction error stay unknown without separate measurements. JUnit aggregate
durations remain visible but cannot substitute for process intervals.

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
    - uses: gigaverse-app/ci-esta/actions/ci-observability@v1
      with:
        github-token: ${{ github.token }}
        required-gates-json: '[{"kind":"actions_job","job_name":"Validation gate"}]'
        post-sticky: 'false'
        test-selection-artifact: ''
        full-suite-reference-artifact: ''
```

The action installs its Python reporter in an isolated temporary environment. It does not need your application's Python environment or a repository checkout. Composite actions require Bash; the reporting action is validated on Linux runners. The CLI supports Python 3.11+; use the current CI matrix for tested platforms.

An Actions gate selector must provide exactly one of `job_name` (the job's display name, recommended) or legacy `runner_name` (the machine identity from GitHub's API). They are different fields. Duplicate matches leave the gate unobserved rather than choosing an arbitrary job.

Outputs `report-file`, `markdown-file` and `prometheus-file` identify the generated files. Archive them using `actions/upload-artifact`. Reporting steps are best effort; a telemetry outage must not decide whether application validation passes.

To post a sticky PR report, supply `pull-request-number`, set `post-sticky: 'true'`, and grant `pull-requests: write` only in a trusted context. The local CLI never posts comments.

## What the numbers mean

| Measurement | Meaning and limit |
| --- | --- |
| Required-gate elapsed time | Time to the explicitly configured gates, from creation on attempt 1 or the rerun attempt start; topology analysis is a separate opt-in |
| Job admission delay | Time before a job starts, which can include dependencies, approvals and runner queueing |
| Runner seconds | Observed timed jobs across attempts, including retries |
| Slowest step per job | Latest-attempt API step durations, with links to job logs; all steps remain in the JSON report |
| Rounded runner minutes | Sum of per-job ceiling-rounded durations; an estimate, not a GitHub invoice |
| Dollar estimate | Explicit runner rates or GitHub SKU catalog prices multiplied by rounded minutes; withheld when any timed job is unpriced |
| Overlapping prior runs | Observed cost of prior PR runs that overlap the current run |
| Test-selection savings | Optional comparison with comparable full-suite timing references; not a guaranteed counterfactual |

Use `runner-sku-rates-json` for label-to-SKU mappings and optional price overrides. GitHub plans, included usage and discounts are outside this report. Missing gate configuration or API data produces a partial/unavailable report rather than invented precision. Exact run IDs and SHAs belong in the JSON report, not Prometheus grouping labels.

Step timing distinguishes completed, accrued and unavailable measurements. Missing,
skipped or reversed timestamps stay unavailable; a completed step with identical
timestamps is a measured zero at GitHub's timestamp precision. Steps explain job
time and are never added to runner usage. Older v1 reports without steps still load.

## Local reports and offline rendering

```bash
pip install "ci-esta"
# Set GITHUB_TOKEN or GH_TOKEN in your environment; do not put it in command history.
ci-esta report --repository owner/repo --run-id 123456 --gate 'Validation gate'
ci-esta render ci-esta-report/ci-observability.json \
  --markdown report.md --prometheus report.prom
```

Base reporting installs neither pytest nor pytest-selective. Install
`ci-esta[selection]` for Python selection explanations or `ci-esta[pytest]` for
pytest execution tools. The Actions for evidence, gates and change collection do not require a Python application or pytest.

## Prometheus without unbounded labels

`publish-prometheus-snapshot` replaces one stable Pushgateway group using HTTP PUT. It includes repository identity and allows additional bounded labels such as environment or service. Never group by run ID, commit SHA or branch. `failure-mode: warn` is the default; use `fail` only when publication itself is required.

The reporter supports a repository-neutral extension:

```json
{"pytest":{"shard_count":4,"wall_seconds":78,"total_test_seconds":293}}
```

Pass that JSON through `extensions-file`. Existing `backend` and `ai` enrichment profiles remain compatibility adapters for the source consumers, not requirements for new adopters. See [project integrations](integrations.md) for the selection explanation contract.
