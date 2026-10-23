# Public GitHub Actions

Use `gigaverse-app/ci-esta@main` for ci-observability. Specialized actions use
`gigaverse-app/ci-esta/ACTION@main`. Your workflow does not need a checkout of
this toolkit or a Python package installation to load an action. Actions that
analyze your project still need your project's checkout.

## Availability and pinning

These public paths are new on main and are not present in older released tags.
Use a reviewed commit containing the root `action.yml`, or `@main` while evaluating.
After Release Please publishes this feature, use the corresponding compatible
release tag or an immutable commit SHA. Do not change an old version tag to make
new paths appear. Python package versions and installed agent skills are separate:
updating one does not update the others.

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
| `gigaverse-app/ci-esta@main` | [Root action](../action.yml) |
| `gigaverse-app/ci-esta/cancel-obsolete-pr-runs@main` | [cancel-obsolete-pr-runs](../cancel-obsolete-pr-runs/action.yml) |
| `gigaverse-app/ci-esta/ci-observability@main` | [ci-observability](../ci-observability/action.yml) |
| `gigaverse-app/ci-esta/ci-observability-enrichment@main` | [ci-observability-enrichment](../ci-observability-enrichment/action.yml) |
| `gigaverse-app/ci-esta/collect-ci-changes@main` | [collect-ci-changes](../collect-ci-changes/action.yml) |
| `gigaverse-app/ci-esta/collect-pr-changes@main` | [collect-pr-changes](../collect-pr-changes/action.yml) |
| `gigaverse-app/ci-esta/collect-pytest-changes@main` | [collect-pytest-changes](../collect-pytest-changes/action.yml) |
| `gigaverse-app/ci-esta/coverage-policy@main` | [coverage-policy](../coverage-policy/action.yml) |
| `gigaverse-app/ci-esta/current-pr-head@main` | [current-pr-head](../current-pr-head/action.yml) |
| `gigaverse-app/ci-esta/learn-test-timings@main` | [learn-test-timings](../learn-test-timings/action.yml) |
| `gigaverse-app/ci-esta/lint-ci-code@main` | [lint-ci-code](../lint-ci-code/action.yml) |
| `gigaverse-app/ci-esta/native-windows-git@main` | [native-windows-git](../native-windows-git/action.yml) |
| `gigaverse-app/ci-esta/plan-pytest-shards@main` | [plan-pytest-shards](../plan-pytest-shards/action.yml) |
| `gigaverse-app/ci-esta/plan-runner-pools@main` | [plan-runner-pools](../plan-runner-pools/action.yml) |
| `gigaverse-app/ci-esta/postgres-client@main` | [postgres-client](../postgres-client/action.yml) |
| `gigaverse-app/ci-esta/publish-prometheus-snapshot@main` | [publish-prometheus-snapshot](../publish-prometheus-snapshot/action.yml) |
| `gigaverse-app/ci-esta/pytest-canary-pr-state@main` | [pytest-canary-pr-state](../pytest-canary-pr-state/action.yml) |
| `gigaverse-app/ci-esta/pytest-expansion@main` | [pytest-expansion](../pytest-expansion/action.yml) |
| `gigaverse-app/ci-esta/pytest-failure-canary@main` | [pytest-failure-canary](../pytest-failure-canary/action.yml) |
| `gigaverse-app/ci-esta/pytest-timings@main` | [pytest-timings](../pytest-timings/action.yml) |
| `gigaverse-app/ci-esta/resolve-incremental-pr-base@main` | [resolve-incremental-pr-base](../resolve-incremental-pr-base/action.yml) |
| `gigaverse-app/ci-esta/resolve-lane-evidence@main` | [resolve-lane-evidence](../resolve-lane-evidence/action.yml) |
| `gigaverse-app/ci-esta/resolve-pytest-evidence@main` | [resolve-pytest-evidence](../resolve-pytest-evidence/action.yml) |
| `gigaverse-app/ci-esta/resolve-security-trigger@main` | [resolve-security-trigger](../resolve-security-trigger/action.yml) |
| `gigaverse-app/ci-esta/reuse-ecr-image@main` | [reuse-ecr-image](../reuse-ecr-image/action.yml) |
| `gigaverse-app/ci-esta/run-bun-tests@main` | [run-bun-tests](../run-bun-tests/action.yml) |
| `gigaverse-app/ci-esta/semgrep-scan@main` | [semgrep-scan](../semgrep-scan/action.yml) |
| `gigaverse-app/ci-esta/semgrep-scan-ci-code@main` | [semgrep-scan-ci-code](../semgrep-scan-ci-code/action.yml) |
| `gigaverse-app/ci-esta/setup-cached-uv@main` | [setup-cached-uv](../setup-cached-uv/action.yml) |
| `gigaverse-app/ci-esta/setup-python-uv@main` | [setup-python-uv](../setup-python-uv/action.yml) |
| `gigaverse-app/ci-esta/test-impact@main` | [test-impact](../test-impact/action.yml) |
| `gigaverse-app/ci-esta/trivy-scan-ci-code@main` | [trivy-scan-ci-code](../trivy-scan-ci-code/action.yml) |
| `gigaverse-app/ci-esta/trivy-scan-image@main` | [trivy-scan-image](../trivy-scan-image/action.yml) |
| `gigaverse-app/ci-esta/typecheck-scope@main` | [typecheck-scope](../typecheck-scope/action.yml) |
| `gigaverse-app/ci-esta/validation-gate@main` | [validation-gate](../validation-gate/action.yml) |
| `gigaverse-app/ci-esta/verify-pytest-completion@main` | [verify-pytest-completion](../verify-pytest-completion/action.yml) |

Reusable workflows are a different interface: GitHub requires them to live under
`.github/workflows/` and callers use `jobs.<job>.uses`. Actions use
`jobs.<job>.steps[].uses`. The root action is for a step, not a replacement for a
reusable workflow at job level.
