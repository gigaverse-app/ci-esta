# Public GitHub Actions

Use `gigaverse-app/ci-esta@v1` for ci-observability. Specialized actions use
`gigaverse-app/ci-esta/ACTION@v1`. Your workflow does not need a checkout of
this toolkit or a Python package installation to load an action. Actions that
analyze your project still need your project's checkout.

## Availability and pinning

The root and short action paths are available from `v1.0.0`. Use `@v1` for
automatic compatible minor and patch upgrades within 1.x. The publish workflow
advances `v1` only after full release validation and successful publication.
Breaking changes ship under a new major tag, so `v1` never advances to 2.x.
Prereleases do not advance the alias. For a fixed revision, use an exact release
tag such as `@v1.0.0` or an immutable commit SHA. Full release tags are never moved.
Python package versions and installed agent skills are separate: updating one
does not update the others.

Existing `.github/actions/NAME` paths continue to work with the same inputs,
outputs and defaults. Public entry points delegate to those implementations at
the **same pinned revision**; no second implementation or floating nested pin is
involved. Maintainers regenerate metadata with
`uv run python scripts/public_actions.py`; CI checks the forwarding contracts.

Public wrappers use GitHub's self-repository reference (`$/`), supported on
GitHub.com with runner 2.336.0 or newer. For older self-hosted runners or GitHub
Enterprise Server without that syntax, retain the compatibility paths and their
existing version pins. [GitHub reference documentation](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax).

## Action reference

Each link below is the public action's complete input/output contract.

| Entry point | Contract |
| --- | --- |
| `gigaverse-app/ci-esta@v1` | [Root action](../action.yml) |
| `gigaverse-app/ci-esta/cancel-obsolete-pr-runs@v1` | [cancel-obsolete-pr-runs](../cancel-obsolete-pr-runs/action.yml) |
| `gigaverse-app/ci-esta/ci-observability@v1` | [ci-observability](../ci-observability/action.yml) |
| `gigaverse-app/ci-esta/ci-observability-enrichment@v1` | [ci-observability-enrichment](../ci-observability-enrichment/action.yml) |
| `gigaverse-app/ci-esta/collect-ci-changes@v1` | [collect-ci-changes](../collect-ci-changes/action.yml) |
| `gigaverse-app/ci-esta/collect-pr-changes@v1` | [collect-pr-changes](../collect-pr-changes/action.yml) |
| `gigaverse-app/ci-esta/collect-pytest-changes@v1` | [collect-pytest-changes](../collect-pytest-changes/action.yml) |
| `gigaverse-app/ci-esta/coverage-policy@v1` | [coverage-policy](../coverage-policy/action.yml) |
| `gigaverse-app/ci-esta/current-pr-head@v1` | [current-pr-head](../current-pr-head/action.yml) |
| `gigaverse-app/ci-esta/learn-test-timings@v1` | [learn-test-timings](../learn-test-timings/action.yml) |
| `gigaverse-app/ci-esta/lint-ci-code@v1` | [lint-ci-code](../lint-ci-code/action.yml) |
| `gigaverse-app/ci-esta/native-windows-git@v1` | [native-windows-git](../native-windows-git/action.yml) |
| `gigaverse-app/ci-esta/plan-pytest-shards@v1` | [plan-pytest-shards](../plan-pytest-shards/action.yml) |
| `gigaverse-app/ci-esta/plan-runner-pools@v1` | [plan-runner-pools](../plan-runner-pools/action.yml) |
| `gigaverse-app/ci-esta/postgres-client@v1` | [postgres-client](../postgres-client/action.yml) |
| `gigaverse-app/ci-esta/publish-prometheus-snapshot@v1` | [publish-prometheus-snapshot](../publish-prometheus-snapshot/action.yml) |
| `gigaverse-app/ci-esta/pytest-canary-pr-state@v1` | [pytest-canary-pr-state](../pytest-canary-pr-state/action.yml) |
| `gigaverse-app/ci-esta/pytest-expansion@v1` | [pytest-expansion](../pytest-expansion/action.yml) |
| `gigaverse-app/ci-esta/pytest-failure-canary@v1` | [pytest-failure-canary](../pytest-failure-canary/action.yml) |
| `gigaverse-app/ci-esta/pytest-timings@v1` | [pytest-timings](../pytest-timings/action.yml) |
| `gigaverse-app/ci-esta/resolve-incremental-pr-base@v1` | [resolve-incremental-pr-base](../resolve-incremental-pr-base/action.yml) |
| `gigaverse-app/ci-esta/resolve-lane-evidence@v1` | [resolve-lane-evidence](../resolve-lane-evidence/action.yml) |
| `gigaverse-app/ci-esta/resolve-pytest-evidence@v1` | [resolve-pytest-evidence](../resolve-pytest-evidence/action.yml) |
| `gigaverse-app/ci-esta/resolve-security-trigger@v1` | [resolve-security-trigger](../resolve-security-trigger/action.yml) |
| `gigaverse-app/ci-esta/reuse-ecr-image@v1` | [reuse-ecr-image](../reuse-ecr-image/action.yml) |
| `gigaverse-app/ci-esta/report-bun-tests@v1` | [report-bun-tests](../report-bun-tests/action.yml) |
| `gigaverse-app/ci-esta/run-bun-tests@v1` | [run-bun-tests](../run-bun-tests/action.yml) |
| `gigaverse-app/ci-esta/semgrep-scan@v1` | [semgrep-scan](../semgrep-scan/action.yml) |
| `gigaverse-app/ci-esta/semgrep-scan-ci-code@v1` | [semgrep-scan-ci-code](../semgrep-scan-ci-code/action.yml) |
| `gigaverse-app/ci-esta/setup-cached-uv@v1` | [setup-cached-uv](../setup-cached-uv/action.yml) |
| `gigaverse-app/ci-esta/setup-python-uv@v1` | [setup-python-uv](../setup-python-uv/action.yml) |
| `gigaverse-app/ci-esta/test-impact@v1` | [test-impact](../test-impact/action.yml) |
| `gigaverse-app/ci-esta/trivy-scan-ci-code@v1` | [trivy-scan-ci-code](../trivy-scan-ci-code/action.yml) |
| `gigaverse-app/ci-esta/trivy-scan-image@v1` | [trivy-scan-image](../trivy-scan-image/action.yml) |
| `gigaverse-app/ci-esta/typecheck-scope@v1` | [typecheck-scope](../typecheck-scope/action.yml) |
| `gigaverse-app/ci-esta/validation-gate@v1` | [validation-gate](../validation-gate/action.yml) |
| `gigaverse-app/ci-esta/verify-pytest-completion@v1` | [verify-pytest-completion](../verify-pytest-completion/action.yml) |

Reusable workflows are a different interface: GitHub requires them to live under
`.github/workflows/` and callers use `jobs.<job>.uses`. Actions use
`jobs.<job>.steps[].uses`. The root action is for a step, not a replacement for a
reusable workflow at job level.
