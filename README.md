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
# Add after your existing aggregate gate. Replace its display name below.
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

The report appears in the job summary. Pin a reviewed commit SHA instead of `main` for production. See [the observability guide](docs/github-actions-observability.md) for artifacts, costs, local CLI usage and Prometheus. Then adopt [evidence reuse and strict gates](docs/evidence-reuse.md). Our [own workflow](.github/workflows/ci.yml) is a complete example.

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

## Related projects

- [pytest-selective](https://github.com/gigaverse-app/pytest-selective) chooses affected Python tests and explains the selection. CI-esta imports its explanation models instead of maintaining a second copy.
- [pytest-obligation](https://github.com/gigaverse-app/pytest-obligation) tests crash, retry, lost-message and competing-operation guarantees. A reused CI lane is not itself a conformance certificate.
- [Due](https://github.com/gigaverse-app/due) records and recovers durable application work for Django/PostgreSQL/Celery. CI-esta addresses the validation workflow around that application.

See [how the projects fit together](docs/integrations.md). Each can be adopted independently.

## Documentation

| Goal | Read |
| --- | --- |
| Find slow jobs and estimate runner costs | [GitHub Actions observability](docs/github-actions-observability.md) |
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

CI-esta consolidates reusable CI execution, measurement and evidence tooling. The selectors themselves live in [pytest-selective](https://github.com/gigaverse-app/pytest-selective); source obligations live in [pytest-obligation](https://github.com/gigaverse-app/pytest-obligation); dependency maintenance lives in [due](https://github.com/gigaverse-app/due).

| Area | Tools | Python / pytest dependency |
| --- | --- | --- |
| GitHub Actions evidence | Independent lane receipts, incremental PR bases, inventory reuse, validation gates, stale-run cancellation | No pytest required |
| Reporting | Run latency, critical dependencies, all-attempt runner cost, sticky summaries, Prometheus snapshots | Python CLI; accepts non-Python workflows |
| Test execution | JUnit aggregation, duration merge, coverage floors, prior-failure canaries, local shard supervisor, completion receipts | pytest adapters; JUnit and coverage readers are reusable |
| Selection integration | Cached impact planning, shard sizing, type-check scope | Calls pytest-selective; no copied selector |
| Test hygiene | Import isolation, import boundaries, fixture expansion guard | Python source analysis |
| Security and CI lint | Semgrep, Trivy, actionlint, shellcheck, changed diagnostic filtering | Any GitHub repository; scanner prerequisites apply |
| Container evidence | OCI layer comparison, pull experiments, frozen runtime observers, Kubernetes node probes, ECR manifest reuse | Python orchestration; Docker/AWS/Kubernetes providers |
| Live CI drills | Repeated-head, retag, main-moved and readiness scenarios with leased disposable PR slots | Existing Gigaverse consumer profiles; requires explicit live credentials |

See the [action catalog](.github/actions/README.md), [migration inventory](docs/migration-inventory.json) and [preservation test plan](docs/migration-test-plan.md). Some actions retain the originating project's defaults (Python 3.14, coverage schedule, security labels); review their documented inputs. The optional dependency-token receipt adapter recognizes backend-common pins. Without that adapter, evidence uses exact dependency pins.

The wheel includes action support resources. `ci_esta.resources.source_root()` locates them for compatibility imports; normal Actions users should use immutable GitHub `uses:` references. Install `ci-esta[pytest]` when loading `ci_esta.testing.pytest_completion` as a pytest plugin.
