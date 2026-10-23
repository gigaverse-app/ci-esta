# Public GitHub Actions

Use `gigaverse-app/ci-esta@main` for ci-observability. Specialized actions use
`gigaverse-app/ci-esta/actions/ACTION@main`. Your workflow does not need a checkout of
this toolkit or a Python package installation to load an action. Actions that
analyze your project still need your project's checkout.

## Availability and pinning

The shared `actions/NAME` paths are new on main. Use `@main` for evaluation or
a reviewed commit containing them until a published release includes these paths.
Then use the compatible release tag. The planned `@v1` alias provides automatic
compatible minor and patch upgrades within 1.x. The publish workflow
advances `v1` only after full release validation and successful publication.
Breaking changes ship under a new major tag, so `v1` never advances to 2.x.
Prereleases do not advance the alias. For a fixed revision, use an exact release
tag such as `@v1.0.0` or an immutable commit SHA. Full release tags are never moved.
Python package versions and installed agent skills are separate: updating one
does not update the others.

Use `actions/NAME` for new workflows. Existing `.github/actions/NAME` and
top-level `NAME` paths remain compatibility aliases with the same inputs,
outputs and defaults. The root action remains the default reporting entry point.
Public entry points delegate to the canonical implementations at
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
| `gigaverse-app/ci-esta/actions/cancel-obsolete-pr-runs@main` | [cancel-obsolete-pr-runs](../actions/cancel-obsolete-pr-runs/action.yml) |
| `gigaverse-app/ci-esta/actions/ci-observability@main` | [ci-observability](../actions/ci-observability/action.yml) |
| `gigaverse-app/ci-esta/actions/ci-observability-enrichment@main` | [ci-observability-enrichment](../actions/ci-observability-enrichment/action.yml) |
| `gigaverse-app/ci-esta/actions/collect-ci-changes@main` | [collect-ci-changes](../actions/collect-ci-changes/action.yml) |
| `gigaverse-app/ci-esta/actions/collect-pr-changes@main` | [collect-pr-changes](../actions/collect-pr-changes/action.yml) |
| `gigaverse-app/ci-esta/actions/collect-pytest-changes@main` | [collect-pytest-changes](../actions/collect-pytest-changes/action.yml) |
| `gigaverse-app/ci-esta/actions/coverage-policy@main` | [coverage-policy](../actions/coverage-policy/action.yml) |
| `gigaverse-app/ci-esta/actions/current-pr-head@main` | [current-pr-head](../actions/current-pr-head/action.yml) |
| `gigaverse-app/ci-esta/actions/learn-test-timings@main` | [learn-test-timings](../actions/learn-test-timings/action.yml) |
| `gigaverse-app/ci-esta/actions/lint-ci-code@main` | [lint-ci-code](../actions/lint-ci-code/action.yml) |
| `gigaverse-app/ci-esta/actions/native-windows-git@main` | [native-windows-git](../actions/native-windows-git/action.yml) |
| `gigaverse-app/ci-esta/actions/plan-pytest-shards@main` | [plan-pytest-shards](../actions/plan-pytest-shards/action.yml) |
| `gigaverse-app/ci-esta/actions/plan-runner-pools@main` | [plan-runner-pools](../actions/plan-runner-pools/action.yml) |
| `gigaverse-app/ci-esta/actions/postgres-client@main` | [postgres-client](../actions/postgres-client/action.yml) |
| `gigaverse-app/ci-esta/actions/publish-prometheus-snapshot@main` | [publish-prometheus-snapshot](../actions/publish-prometheus-snapshot/action.yml) |
| `gigaverse-app/ci-esta/actions/pytest-canary-pr-state@main` | [pytest-canary-pr-state](../actions/pytest-canary-pr-state/action.yml) |
| `gigaverse-app/ci-esta/actions/pytest-expansion@main` | [pytest-expansion](../actions/pytest-expansion/action.yml) |
| `gigaverse-app/ci-esta/actions/pytest-failure-canary@main` | [pytest-failure-canary](../actions/pytest-failure-canary/action.yml) |
| `gigaverse-app/ci-esta/actions/pytest-timings@main` | [pytest-timings](../actions/pytest-timings/action.yml) |
| `gigaverse-app/ci-esta/actions/resolve-incremental-pr-base@main` | [resolve-incremental-pr-base](../actions/resolve-incremental-pr-base/action.yml) |
| `gigaverse-app/ci-esta/actions/resolve-lane-evidence@main` | [resolve-lane-evidence](../actions/resolve-lane-evidence/action.yml) |
| `gigaverse-app/ci-esta/actions/resolve-pytest-evidence@main` | [resolve-pytest-evidence](../actions/resolve-pytest-evidence/action.yml) |
| `gigaverse-app/ci-esta/actions/resolve-security-trigger@main` | [resolve-security-trigger](../actions/resolve-security-trigger/action.yml) |
| `gigaverse-app/ci-esta/actions/reuse-ecr-image@main` | [reuse-ecr-image](../actions/reuse-ecr-image/action.yml) |
| `gigaverse-app/ci-esta/actions/report-bun-tests@main` | [report-bun-tests](../actions/report-bun-tests/action.yml) |
| `gigaverse-app/ci-esta/actions/run-bun-tests@main` | [run-bun-tests](../actions/run-bun-tests/action.yml) |
| `gigaverse-app/ci-esta/actions/semgrep-scan@main` | [semgrep-scan](../actions/semgrep-scan/action.yml) |
| `gigaverse-app/ci-esta/actions/semgrep-scan-ci-code@main` | [semgrep-scan-ci-code](../actions/semgrep-scan-ci-code/action.yml) |
| `gigaverse-app/ci-esta/actions/setup-cached-uv@main` | [setup-cached-uv](../actions/setup-cached-uv/action.yml) |
| `gigaverse-app/ci-esta/actions/setup-python-uv@main` | [setup-python-uv](../actions/setup-python-uv/action.yml) |
| `gigaverse-app/ci-esta/actions/test-impact@main` | [test-impact](../actions/test-impact/action.yml) |
| `gigaverse-app/ci-esta/actions/trivy-scan-ci-code@main` | [trivy-scan-ci-code](../actions/trivy-scan-ci-code/action.yml) |
| `gigaverse-app/ci-esta/actions/trivy-scan-image@main` | [trivy-scan-image](../actions/trivy-scan-image/action.yml) |
| `gigaverse-app/ci-esta/actions/typecheck-scope@main` | [typecheck-scope](../actions/typecheck-scope/action.yml) |
| `gigaverse-app/ci-esta/actions/validation-gate@main` | [validation-gate](../actions/validation-gate/action.yml) |
| `gigaverse-app/ci-esta/actions/verify-pytest-completion@main` | [verify-pytest-completion](../actions/verify-pytest-completion/action.yml) |

Reusable workflows are a different interface: GitHub requires them to live under
`.github/workflows/` and callers use `jobs.<job>.uses`. Actions use
`jobs.<job>.steps[].uses`. The root action is for a step, not a replacement for a
reusable workflow at job level.
