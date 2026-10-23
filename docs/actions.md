# Public GitHub Actions

Use `gigaverse-app/ci-esta/actions/ci-observability@v1` for reports. All actions use
`gigaverse-app/ci-esta/actions/NAME@v1`. Your workflow does not need a checkout of
this toolkit or a Python package installation to load an action. Actions that
analyze your project still need your project's checkout.

## Availability and pinning

Use `actions/NAME@v1` for the current Actions API. Its moving major tag is
independent of the Python package version and advances only after the exact
commit passes main CI and the public action smoke. Python dependency ranges and installed
agent skills are separate. Use an immutable full release tag or commit when a
fixed revision is required. Prereleases do not advance `v1`.

Each `actions/NAME` directory contains the implementation and its helper files.
The former `.github/actions/NAME` and top-level `NAME` directories have been
removed from main. Update the path and revision together when migrating:
`gigaverse-app/ci-esta/actions/NAME@REVISION`. Old immutable releases keep their
original layouts; a new path cannot be used with a release that predates it.

The former root action is also removed. Replace `gigaverse-app/ci-esta@REVISION`
with `gigaverse-app/ci-esta/actions/ci-observability@v1`. Every entry point runs its
implementation directly; there are no generated aliases.

## Action reference

Each link below is the public action's complete input/output contract.

Opt in to partial-run retention with the matching `restore-test-timings` action and
a stable `history-key`. See the [executable retention tutorial](learned-test-timings.md#retain-history-across-partial-runs).


| Entry point | Contract |
| --- | --- |
| `gigaverse-app/ci-esta/actions/cancel-obsolete-pr-runs@v1` | [cancel-obsolete-pr-runs](../actions/cancel-obsolete-pr-runs/action.yml) |
| `gigaverse-app/ci-esta/actions/ci-observability@v1` | [ci-observability](../actions/ci-observability/action.yml) |
| `gigaverse-app/ci-esta/actions/ci-observability-enrichment@v1` | [ci-observability-enrichment](../actions/ci-observability-enrichment/action.yml) |
| `gigaverse-app/ci-esta/actions/collect-ci-changes@v1` | [collect-ci-changes](../actions/collect-ci-changes/action.yml) |
| `gigaverse-app/ci-esta/actions/collect-pr-changes@v1` | [collect-pr-changes](../actions/collect-pr-changes/action.yml) |
| `gigaverse-app/ci-esta/actions/collect-pytest-changes@v1` | [collect-pytest-changes](../actions/collect-pytest-changes/action.yml) |
| `gigaverse-app/ci-esta/actions/coverage-policy@v1` | [coverage-policy](../actions/coverage-policy/action.yml) |
| `gigaverse-app/ci-esta/actions/current-pr-head@v1` | [current-pr-head](../actions/current-pr-head/action.yml) |
| `gigaverse-app/ci-esta/actions/learn-test-timings@v1` | [learn-test-timings](../actions/learn-test-timings/action.yml) |
| `gigaverse-app/ci-esta/actions/lint-ci-code@v1` | [lint-ci-code](../actions/lint-ci-code/action.yml) |
| `gigaverse-app/ci-esta/actions/native-windows-git@v1` | [native-windows-git](../actions/native-windows-git/action.yml) |
| `gigaverse-app/ci-esta/actions/plan-pytest-shards@v1` | [plan-pytest-shards](../actions/plan-pytest-shards/action.yml) |
| `gigaverse-app/ci-esta/actions/plan-runner-pools@v1` | [plan-runner-pools](../actions/plan-runner-pools/action.yml) |
| `gigaverse-app/ci-esta/actions/postgres-client@v1` | [postgres-client](../actions/postgres-client/action.yml) |
| `gigaverse-app/ci-esta/actions/publish-prometheus-snapshot@v1` | [publish-prometheus-snapshot](../actions/publish-prometheus-snapshot/action.yml) |
| `gigaverse-app/ci-esta/actions/pytest-canary-pr-state@v1` | [pytest-canary-pr-state](../actions/pytest-canary-pr-state/action.yml) |
| `gigaverse-app/ci-esta/actions/pytest-expansion@v1` | [pytest-expansion](../actions/pytest-expansion/action.yml) |
| `gigaverse-app/ci-esta/actions/pytest-failure-canary@v1` | [pytest-failure-canary](../actions/pytest-failure-canary/action.yml) |
| `gigaverse-app/ci-esta/actions/pytest-timings@v1` | [pytest-timings](../actions/pytest-timings/action.yml) |
| `gigaverse-app/ci-esta/actions/resolve-incremental-pr-base@v1` | [resolve-incremental-pr-base](../actions/resolve-incremental-pr-base/action.yml) |
| `gigaverse-app/ci-esta/actions/resolve-lane-evidence@v1` | [resolve-lane-evidence](../actions/resolve-lane-evidence/action.yml) |
| `gigaverse-app/ci-esta/actions/resolve-pytest-evidence@v1` | [resolve-pytest-evidence](../actions/resolve-pytest-evidence/action.yml) |
| `gigaverse-app/ci-esta/actions/resolve-security-trigger@v1` | [resolve-security-trigger](../actions/resolve-security-trigger/action.yml) |
| `gigaverse-app/ci-esta/actions/restore-test-timings@v1` | [restore-test-timings](../actions/restore-test-timings/action.yml) |
| `gigaverse-app/ci-esta/actions/reuse-ecr-image@v1` | [reuse-ecr-image](../actions/reuse-ecr-image/action.yml) |
| `gigaverse-app/ci-esta/actions/report-bun-tests@v1` | [report-bun-tests](../actions/report-bun-tests/action.yml) |
| `gigaverse-app/ci-esta/actions/run-bun-tests@v1` | [run-bun-tests](../actions/run-bun-tests/action.yml) |
| `gigaverse-app/ci-esta/actions/semgrep-scan@v1` | [semgrep-scan](../actions/semgrep-scan/action.yml) |
| `gigaverse-app/ci-esta/actions/semgrep-scan-ci-code@v1` | [semgrep-scan-ci-code](../actions/semgrep-scan-ci-code/action.yml) |
| `gigaverse-app/ci-esta/actions/setup-cached-uv@v1` | [setup-cached-uv](../actions/setup-cached-uv/action.yml) |
| `gigaverse-app/ci-esta/actions/setup-python-uv@v1` | [setup-python-uv](../actions/setup-python-uv/action.yml) |
| `gigaverse-app/ci-esta/actions/test-impact@v1` | [test-impact](../actions/test-impact/action.yml) |
| `gigaverse-app/ci-esta/actions/trivy-scan-ci-code@v1` | [trivy-scan-ci-code](../actions/trivy-scan-ci-code/action.yml) |
| `gigaverse-app/ci-esta/actions/trivy-scan-image@v1` | [trivy-scan-image](../actions/trivy-scan-image/action.yml) |
| `gigaverse-app/ci-esta/actions/typecheck-scope@v1` | [typecheck-scope](../actions/typecheck-scope/action.yml) |
| `gigaverse-app/ci-esta/actions/validation-gate@v1` | [validation-gate](../actions/validation-gate/action.yml) |
| `gigaverse-app/ci-esta/actions/verify-pytest-completion@v1` | [verify-pytest-completion](../actions/verify-pytest-completion/action.yml) |

Reusable workflows are a different interface: GitHub requires them to live under
`.github/workflows/` and callers use `jobs.<job>.uses`. Actions use
`jobs.<job>.steps[].uses`.
