# CI-esta: faster GitHub Actions with evidence

[![CI](https://github.com/gigaverse-app/ci-esta/actions/workflows/ci.yml/badge.svg)](https://github.com/gigaverse-app/ci-esta/actions/workflows/ci.yml)
[![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-blue)](pyproject.toml)
[![Apache 2.0](https://img.shields.io/badge/license-Apache--2.0-blue)](LICENSE)

Let proven work rest. Measure the rest.

CI-esta is an open-source toolkit for **GitHub Actions optimization and CI observability**. It measures where a workflow spends time and reuses successful validation only when matching execution evidence exists. Your application can use any language.

Repeated CI work is easy to skip incorrectly: the previous workflow was green but the relevant lane never ran, the PR base moved, a newer rerun failed, or the change list was incomplete. CI-esta makes those decisions explicit and falls back to doing the work when proof is uncertain.

## What is included

| Tool | What it does |
| --- | --- |
| `ci-observability` | Required-gate latency, job admission delay, all-attempt runner time, configured cost estimates, overlapping runs; JSON, Markdown and Prometheus |
| `resolve-lane-evidence` | Reuse a passing lane with a matching completion receipt, bounded freshness and conservative failure handling |
| `resolve-incremental-pr-base` | Find a proven successful ancestor for incremental scanners; fall back to the PR base |
| `validation-gate` | Fail on missing, failed, cancelled or unexpectedly skipped prerequisites |
| `collect-pr-changes` | Collect a complete PR file list bound to the observed head and base; detect truncation and races |
| `publish-prometheus-snapshot` | Replace a stable, repository-isolated Pushgateway group without run/SHA label growth |

All actions live in this repository. No hosted CI-esta service is required. Evidence and gate actions use JavaScript; reporting uses an isolated Python runtime. A pytest application is not required.

## Start by measuring one workflow

```yaml
# .github/workflows/observe-ci.yml
name: CI observability
on:
  workflow_run:
    workflows: [CI] # Your validation workflow's name
    types: [completed]
permissions:
  contents: read
  actions: read
  checks: read
  pull-requests: read
jobs:
  report:
    uses: gigaverse-app/ci-esta/.github/workflows/report.yml@f96bfac9203368be10cd4cf0f117471441636080
    with:
      run-id: ${{ github.event.workflow_run.id }}
      run-attempt: ${{ github.event.workflow_run.run_attempt }}
      head-sha: ${{ github.event.workflow_run.head_sha }}
      required-gates-json: '[{"kind":"actions_job","job_name":"Validation gate"}]'
```

Replace the workflow and required job names with yours. Commit this observer to
your default branch; it reports future completed runs without becoming a
validation prerequisite. The pinned reusable workflow writes a summary and
JSON/Markdown/Prometheus artifacts with read-only permissions. See
[the observability guide](docs/github-actions-observability.md) for costs and
local CLI usage, then adopt [evidence reuse and strict gates](docs/evidence-reuse.md).
Our [validation workflow](.github/workflows/ci.yml) and
[observer](.github/workflows/observe-ci.yml) are complete examples.

## Who runs CI-esta

| Project | Runs | What it bought |
| --- | --- | --- |
| [Due](https://github.com/gigaverse-app/due) | [Reports](https://github.com/gigaverse-app/due/blob/main/.github/workflows/observe-ci.yml) and the [required-check gate](https://github.com/gigaverse-app/due/blob/main/.github/workflows/ci.yml) | The gate lets a docs-only PR skip the test matrix while required checks `tests (locked)` and `tests (minimum)` still report. With pytest-selective, a library-test change finishes main CI in **3m24s instead of 6m03s**. Reports surfaced 404–431s CPU-profiling steps, now being cut in [Due #72](https://github.com/gigaverse-app/due/pull/72). |
| [pytest-obligation](https://github.com/gigaverse-app/pytest-obligation) | [Reports](https://github.com/gigaverse-app/pytest-obligation/blob/main/.github/workflows/observe-ci.yml) | A package README change uses **57 runner-seconds instead of 1,691**. The observer replaced an inline timing job, so validation no longer waits for telemetry ([#98](https://github.com/gigaverse-app/pytest-obligation/pull/98)). |
| [pytest-selective](https://github.com/gigaverse-app/pytest-selective) | [Reports](https://github.com/gigaverse-app/pytest-selective/blob/main/.github/workflows/observe-ci.yml) | Found a 279s Windows job on a 295s validation path, for **19 runner-seconds** of reporting. |

The skipped-lane savings come from [pytest-selective](https://github.com/gigaverse-app/pytest-selective)
routing; CI-esta's part is the gate that keeps a skip honest and the reports that
show what to cut next. CI-esta also renders pytest-selective's selection
explanations, importing its models instead of keeping a copy. A reused lane is
not a conformance certificate: Due and pytest-obligation keep their executed
[pytest-obligation](https://github.com/gigaverse-app/pytest-obligation) evidence
checks. See [how the projects fit together](docs/integrations.md).

## What measured runs show

Explicit input routing with [pytest-selective](https://github.com/gigaverse-app/pytest-selective)
reduced work in these successful GitHub Actions pairs:

| Change | Full runner-seconds | Selected runner-seconds | Reduction |
| --- | ---: | ---: | ---: |
| pytest-selective README | 627 | 48 | 92.3% |
| Due library test, main CI | 747 | 388 | 48.1% |
| pytest-obligation MongoDB test | 1,602 | 93 | 94.2% |
| pytest-obligation package README | 1,691 | 57 | 96.6% |

These are one sequential pair per scenario on the same PR head and merge
checkout, including planner overhead.
[Raw timestamps, run links and limitations](https://github.com/gigaverse-app/pytest-selective/blob/main/docs/benchmarks/2026-10-22.md)
are published with the selector. Runner-seconds sum executed-job durations;
they are not billed minutes. Due's separate widget benchmark is excluded here.
**These savings come from selection and consumer input declarations, not
CI-esta receipt reuse.**

The [README-only paired experiment](https://github.com/gigaverse-app/pytest-selective/blob/main/docs/benchmarks/2026-10-22-routing.md)
also reduced pytest-selective's elapsed time from **211s to 26s**, retaining
routing regressions, docs and package validation. The same report records a
Due docs-only preservation check at **26s elapsed / 91 runner-seconds**; it has
no paired control and is not presented as a measured speedup.

CI-esta makes the next optimization visible. In a
[real pytest-selective report](docs/benchmarks/2026-10-22-selective-report.md),
required jobs completed in **295s**. The slowest Windows job took **279s**;
all jobs totaled **731 runner-seconds**. Its separate completed-run reporter
used **19s** of runner time and was not a validation prerequisite.
[How this was measured](docs/benchmarks/2026-10-22.md) includes the source JSON,
run identities and limits.

Start with reporting, then narrow inputs and preserve full checkpoints. For
Due and pytest-obligation conformance lanes, review every runtime/configuration
input before enabling receipt reuse. A previous green workflow alone is
insufficient evidence.

## What a reused lane means

```text
declared inputs + actual tool bytes
             |
       matching receipt?
       /             \
fresh passing      missing, stale,
lane found         failed or uncertain
    |                    |
reuse evidence       execute lane
       \             /
        strict aggregate gate
```

Receipts are recorded only after required work passes. Explicit reruns execute again. Missing or contradictory evidence must not silently green the merge gate. Input declarations remain your responsibility: a changed external service cannot be inferred from an unchanged Git tree.

## Documentation

| Goal | Read |
| --- | --- |
| Find slow jobs and estimate runner costs | [GitHub Actions observability](docs/github-actions-observability.md) |
| Diagnose slow Python CI without cutting checks | [Python CI tuning](docs/python-ci-tuning.md) |
| Avoid repeating proven work | [Evidence reuse](docs/evidence-reuse.md) |
| Integrate selection and conformance tests | [Project integrations](docs/integrations.md) |
| Compare CI optimization approaches | [Alternatives](docs/alternatives.md) |
| Understand extraction scope and migration | [Upstreaming](docs/upstreaming.md) |
| Run tests and contribute | [Contributing](CONTRIBUTING.md) |

## Status and limits

**Alpha, extracted from Gigaverse's backend-common CI tools.** APIs and schemas may evolve. Git installs work; no PyPI or npm release is claimed. The reporting package currently installs pytest-selective from a pinned public Git revision. Python 3.11+ is required for the CLI; Actions do not require your application to use Python.

Cost figures are estimates using configured rates, not billing records. Admission delay includes more than runner queue time. Evidence reuse is bounded by declared inputs, proof freshness and GitHub API visibility. No universal speedup is claimed. The backend-common compatibility migration is tracked separately from publication; see [adoption](docs/upstreaming.md).

Apache-2.0. See [source provenance](PROVENANCE.md).


## CI toolkit catalog

CI-esta consolidates reusable CI execution, measurement and evidence tooling. Selection and test-isolation guards live in [pytest-selective](https://github.com/gigaverse-app/pytest-selective); durable-work conformance tests live in [pytest-obligation](https://github.com/gigaverse-app/pytest-obligation); the Django/PostgreSQL/Celery application runtime lives in [Due](https://github.com/gigaverse-app/due).

| Area | Tools | Python / pytest dependency |
| --- | --- | --- |
| GitHub Actions evidence | Independent lane receipts, incremental PR bases, inventory reuse, validation gates, stale-run cancellation | No pytest required |
| Reporting | Run latency, critical dependencies, all-attempt runner cost, sticky summaries, Prometheus snapshots | Python CLI; accepts non-Python workflows |
| Test execution | JUnit aggregation, duration merge, coverage floors, prior-failure canaries, local shard supervisor, completion receipts | pytest adapters; JUnit and coverage readers are reusable |
| Selection integration | Cached impact planning, shard sizing, type-check scope | Calls pytest-selective; no copied selector |
| Test hygiene | Import boundaries; compatibility delegates for pytest-selective's isolation and expansion guards | Python source analysis |
| Security and CI lint | Semgrep, Trivy, actionlint, shellcheck, changed diagnostic filtering | Any GitHub repository; scanner prerequisites apply |
| Container evidence | OCI layer comparison, pull experiments, frozen runtime observers, Kubernetes node probes, ECR manifest reuse | Python orchestration; Docker/AWS/Kubernetes providers |
| Live CI drills | Repeated-head, retag, main-moved and readiness scenarios with leased disposable PR slots | Existing Gigaverse consumer profiles; requires explicit live credentials |

See the [action catalog](.github/actions/README.md), [migration inventory](docs/migration-inventory.json) and [preservation test plan](docs/migration-test-plan.md). Some actions retain the originating project's defaults (Python 3.14, coverage schedule, security labels); review their documented inputs. The optional dependency-token receipt adapter recognizes backend-common pins. Without that adapter, evidence uses exact dependency pins.

The wheel includes action support resources. `ci_esta.resources.source_root()` locates them for compatibility imports; normal Actions users should use immutable GitHub `uses:` references. Install `ci-esta[pytest]` when loading `ci_esta.testing.pytest_completion` as a pytest plugin.
