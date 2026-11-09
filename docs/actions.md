# Public GitHub Actions

Use `gigaverse-app/ci-esta/actions/ci-observability@v1` for reports. All actions use
`gigaverse-app/ci-esta/actions/NAME@v1`. Your workflow does not need a checkout of
this toolkit or a Python package installation to load an action. Actions that
analyze your project still need your project's checkout.

## Availability and pinning

For scheduled full validation, use [`weekly-checkpoint`](weekly-checkpoints.md).
`ci-esta checkpoint init` generates the adopter's schedule with conservative defaults.

For Bun dependency setup, use [`setup-cached-bun`](environment-cache.md#bun-dependency-downloads).
For compiler or tool caches, use [`report-cache`](environment-cache.md#other-download-build-and-tool-caches).
Both publish execution measurements consumed automatically by the report workflow.

Use `actions/NAME@v1` for the current Actions API. Its moving major tag is
independent of the Python package version and advances only after the exact
commit passes main CI and the public action smoke. Python dependency ranges and installed
agent skills are separate. Prereleases do not advance `v1`.

Follow your repository's pinning policy. Without one, use the published major tag
`@v1`. If your workflows pin actions to commit SHAs (for example because zizmor or
an organization policy requires it), pin CI-esta the same way, with the release tag
as a comment, and let Dependabot or Renovate update both:

```yaml
- uses: gigaverse-app/ci-esta/actions/setup-cached-uv@<sha> # v1.8.0
```

Resolve a tag to its commit with `gh api repos/gigaverse-app/ci-esta/commits/v1.8.0 --jq .sha`.
That returns the commit for annotated tags too, where `git/ref/tags/TAG` returns the
tag object instead. Pin a release tag (`v1.8.0`), not the moving `v1`, so the comment
stays true.

Some actions have version floors in the environment they run in:
`setup-cached-uv` always runs `uv sync --locked`, so it needs a committed `uv.lock`;
without one, keep your existing Python setup or use `astral-sh/setup-uv` with its cache.
The pytest completion-receipt plugin (`-p ci_esta.testing.pytest_completion`) runs
inside your pytest process, so that environment needs Python 3.11+, CI-esta's floor.
For jobs testing older interpreters, gate each test job directly and use its own
inventory (JUnit, tox `--result-json`) instead of receipts; never write a receipt
with a shell `echo $?`, because pytest also exits 1 without finishing. Actions that
install their own runtime, such as `plan-runner-pools` and `ci-observability`, have
no floor for your project.

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
| `gigaverse-app/ci-esta/actions/observe-deployment@v1` | [observe-deployment](../actions/observe-deployment/action.yml) |
| `gigaverse-app/ci-esta/actions/plan-pytest-shards@v1` | [plan-pytest-shards](../actions/plan-pytest-shards/action.yml) |
| `gigaverse-app/ci-esta/actions/plan-runner-pools@v1` | [plan-runner-pools](../actions/plan-runner-pools/action.yml) |
| `gigaverse-app/ci-esta/actions/postgres-client@v1` | [postgres-client](../actions/postgres-client/action.yml) |
| `gigaverse-app/ci-esta/actions/publish-prometheus-snapshot@v1` | [publish-prometheus-snapshot](../actions/publish-prometheus-snapshot/action.yml) |
| `gigaverse-app/ci-esta/actions/publish-shard-measurements@v1` | [publish-shard-measurements](../actions/publish-shard-measurements/action.yml) |
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
| `gigaverse-app/ci-esta/actions/plan-work@v1` | [plan-work](../actions/plan-work/action.yml) |
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

## Test execution policy

`plan-test-policy` admits work after impact selection; `check-test-policy` tests project routing contracts against the installed CLI; `test-budget` computes a remaining runtime limit after setup. See [the complete schemas, action map and examples](test-execution-policy.md).
