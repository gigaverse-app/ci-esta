# CI action implementation catalog

Start with the [public action API](../docs/actions.md) and
[quickstart](../docs/quickstart.md). This catalog includes advanced and
consumer-specific tools; they are not all required for adoption.

Reusable pieces so `gigaverse-ai` and `gigaverse-backend` share identical CI
mechanics without forcing repository-specific build and test layouts into one
workflow.

Use `gigaverse-app/ci-esta/actions/<name>@<reviewed-commit>` for the
extracted actions. The backend-common reusable workflows listed below retain
Gigaverse event/security/release policy; they are external compositions, not
workflows shipped by CI-esta. Start with the [portable adoption guide](../docs/ci-optimization.md)
and check the [revision-bound adoption audit](../docs/adoption-audit.md).

Each piece is matched to the shape of the shared work:

| Piece | Kind | Reused by |
|-------|------|-----------|
| [`setup-cached-bun`](../docs/environment-cache.md#bun-dependency-downloads) | composite action | Pinned Bun, locked installation and measured dependency downloads |
| [`report-cache`](../docs/environment-cache.md#other-download-build-and-tool-caches) | composite action | Caller-owned compiler and tool caches with exact/fallback outcomes |
| [`run-bun-tests`](../docs/bun-test-selection.md) | composite action + standalone JS API | Bun source selection with repository-owned inventory and always-run contracts |
| `collect-ci-changes` | composite action | workflow/action/shell change classification |
| `current-pr-head` | composite action | live stale-rerun admission |
| `resolve-security-trigger` | composite action | every security workflow, both repos |
| [`resolve-scheduled-base`](../docs/test-execution-policy.md#daily-affected-validation) | composite action | daily affected selection from executed scheduled ancestors; full fallback on uncertainty |
| `resolve-incremental-pr-base` | composite action | automatic security and CI-code PR validation |
| `trivy-scan-image` | composite action | each repo's Trivy workflow |
| `backend-common/reusable-semgrep.yaml` | reusable workflow | each repo's Semgrep stub |
| `lint-ci-code` | composite action | `backend-common/reusable-ci-code-validation.yaml` |
| `semgrep-scan-ci-code` | composite action | `backend-common/reusable-ci-code-validation.yaml` |
| `trivy-scan-ci-code` | composite action | `backend-common/reusable-ci-code-validation.yaml` |
| `backend-common/reusable-ci-code-validation.yaml` | reusable workflow | path-filtered CI validation callers |
| `backend-common/reusable-current-pr-head.yaml` | reusable workflow | stale manual-rerun admission in PR validation |
| `cancel-obsolete-pr-runs` | composite action | post-admission stale-run cancellation from existing jobs |
| `setup-python-uv` | composite action | backend-common test and type-check workflows |
| `setup-cached-uv` | composite action | portable exact environment restore, repair and locked synchronization |
| [`service-container`](service-container/README.md) | composite action | overlap image downloads with dependency setup while requiring health before tests |
| [`postgres-client`](../docs/postgres-client.md) | composite action | version-matched PostgreSQL dump/restore on Linux Docker runners |
| `publish-prometheus-snapshot` | composite action | bounded CI/build metric producers |
| `ci-observability` | composite action | CI latency/cost sticky and evidence in all three repos |
| `reuse-ecr-image` | composite action | deployments that can reuse an exact verified image |
| `pytest-failure-canary` | composite action | bounded whole-file retries from prior JUnit failures |
| `pytest-canary-pr-state` | composite action | stale-run-safe pytest-red PR label transitions |
| `plan-pytest-shards` | composite action | exhaustive file partitioning with the shared duration planner |
| `resolve-lane-evidence` | composite action | passing-result reuse for whole trees or declared complete input paths |

For stale-rerun safety, first PR attempts use a PR-number concurrency group and
reruns use their unique run ID, so a rerun can never replace or cancel current
work. Call `backend-common/reusable-current-pr-head.yaml` before a rerun's expensive jobs. A
first-attempt job also calls `cancel-obsolete-pr-runs`: this cancels a rerun
that passed admission and then became stale, without adding a runner job. It
resolves the current commit's first parent through check runs, avoiding
GitHub's eventually-consistent workflow-run listing after a normal one-commit
agent push; the workflow index remains the fallback for other histories.

## `ci-observability`

Discovers jobs, commit statuses, and all rerun attempts through GitHub's
paginated API; combines them with explicit required-gate/direct-prerequisite
metadata and optional typed repository signals; and emits a versioned JSON
artifact, sticky/summary Markdown, and bounded Prometheus exposition. Workflow
job names, matrix size, and step ordering are never accounting keys.

```yaml
- uses: gigaverse-app/ci-esta/actions/ci-observability@v1
  with:
    github-token: ${{ github.token }}
    commit-sha: ${{ github.event.pull_request.head.sha }}
    pull-request-number: ${{ github.event.pull_request.number }}
    required-gates-json: >-
      [{"kind":"commit_status","context":"required-check"}]
```

Run it on an existing off-path host. See
[`docs/github-actions-observability.md`](../docs/github-actions-observability.md) for the versioned
data, timing, cost, graph, metric, and failure contracts. When the run's
`test-impact` action uploaded a selection explanation, the sticky opens with a
test-selection section; consumers pass nothing extra for it.

## `reuse-ecr-image`

Promotes an immutable, previously verified image to the tag consumed by a
deployment by copying its ECR manifest inside the same repository. It never
pulls or rebuilds layers. The action emits `reused=false` on a missing image,
registry error, repository mismatch, target conflict, promotion failure, or
digest mismatch so the caller can continue through its ordinary build path.

The caller owns the artifact identity and verification policy. This action only
proves that the source and target ECR references resolve to the same digest.

```yaml
- id: image-reuse
  uses: gigaverse-app/ci-esta/actions/reuse-ecr-image@v1
  with:
    source-image: ${{ env.REPOSITORY }}:verified-${{ steps.identity.outputs.key }}
    target-image: ${{ env.REPOSITORY }}:${{ github.sha }}

- if: steps.image-reuse.outputs.reused != 'true'
  run: ./build-and-push-image.sh
```

## `publish-prometheus-snapshot`

Replaces one stable Pushgateway group from a Prometheus text exposition file.
The action always adds `GITHUB_REPOSITORY` to the grouping key, uses `PUT`, and
handles `/` in grouping values with Pushgateway's required URL-safe base64
encoding.

```yaml
- uses: gigaverse-app/ci-esta/actions/publish-prometheus-snapshot@v1
  with:
    metrics-file: build-metrics.prom
    pushgateway-url: ${{ secrets.PUSHGW_URL }}
    job: docker_build
    grouping-labels: >-
      {"env":"dev","service":"edge_service"}
    username: ghci
    password: ${{ secrets.PUSHGW_PASS }}
```

Grouping labels identify retained state, not individual events:

- Use bounded dimensions such as environment, service, or a persistent branch.
- Never use run IDs or commit SHAs; the action rejects those dimensions.
- For unbounded feature branches, publish only artifacts or add an explicit
  lifecycle cleanup workflow.
- Use `failure-mode: fail` only when publishing telemetry must gate the caller.
  The default `warn` mode reports an annotation without failing delivery work.

## `resolve-security-trigger`

Decides whether a security scan should run, from the same triggers the
non-default test framework uses (`docs/testing/expensive-test-policy.md` in the
consumers): PR `risk:security` label, a write+ collaborator
`/gv-test security` | `@gv-ci run security` comment, push, or manual dispatch.
Emits `should_run`, `ref`, `pr_number`, `mode`, and `same_repo`. For a shared
resolver, leave `require-same-repo` false and gate only secret-bearing consumers
on `same_repo`; source-only scans can still run on forks.

Consumers that produce reusable pre-merge artifacts can set
`automatic-same-repo-pull-requests: "true"`. That admits opened, reopened,
synchronized, and ready-for-review non-draft, non-bot PRs only when their head
branch belongs to the consumer repository. The default remains the opt-in
label/comment policy. Automatic PR scans use the newest successful ancestor
from this exact workflow and PR as their diff base, so later pushes scan only
work that has not already passed. The stable job name or reusable-workflow
suffix named by `automatic-pr-evidence-job-name` must also have succeeded; a
caller prefix such as `validate / ` does not change the evidence identity. A
green workflow whose scan jobs were skipped is not reusable evidence. A
cancelled workflow is reusable only when every job pattern declared by
`automatic-pr-cancelled-evidence-job-patterns` succeeded. Evidence expires
after seven days. A missing or failed run, rewritten branch, API failure, or
any other uncertainty falls back to the PR base and scans the whole PR diff.
Automatic callers grant the resolver job `actions: read`, `checks: read`, and
`contents: read`; cancellation in the same job may require `actions: write`
instead.

`dependency-paths` defines the package manifests, lockfiles, Dockerfiles, and
other inputs that determine an inventory scan. For automatic PRs and pushes,
`deps_changed=false` is emitted only after the compare API proves none of those
paths changed. Explicit label/comment/manual scans and scheduled scans always
emit `true`; comparison uncertainty also fails open to `true`.

For automatic PRs, `semgrep_changed=false` is emitted before scanner job
allocation only when the complete incremental diff contains no added, modified,
or renamed file outside `automatic-pr-ignored-paths`. The defaults contain the
two machine-owned bump provenance files; explicit and uncertain runs stay
fail-open.

```yaml
- id: gate
  uses: gigaverse-app/ci-esta/actions/resolve-security-trigger@v1
  with:
    require-same-repo: "true"   # set for image-building scans (Trivy); needs same-repo secrets
    automatic-same-repo-pull-requests: "true"  # optional; default false
    dependency-paths: |
      pyproject.toml
      uv.lock
      deployment/Dockerfile
```

## `trivy-scan-image`

Runs `aquasecurity/trivy-action` against an already-materialized image or
filesystem package inventory with the shared severity policy (`CRITICAL,HIGH`,
`ignore-unfixed`, fail on findings). Inventory
creation is the consumer's job: use `image-ref` for an OS image, or let the
native package manager materialize an environment and use `scan-type: fs` plus
`scan-ref`. This is important for lock formats with environment markers: Trivy
matches installed package versions to advisories; it does not replace the
package manager's resolution semantics.

The action pins Trivy `v0.72.0` by default; consumers can use `trivy-version`
for a controlled compatibility override. `vuln-type` defaults to both OS and
language libraries, while `scanners` defaults to `vuln`: the shared Semgrep
gate owns source-code vulnerability and secret scanning once at repository
scope. A consumer without that gate must explicitly request the additional
scanner. Callers should similarly narrow `vuln-type` when they deliberately
split package inventories.

```yaml
- uses: gigaverse-app/ci-esta/actions/trivy-scan-image@v1
  with:
    image-ref: "trivy-scan:my_service"
```

```yaml
- run: uv sync --frozen --all-groups --no-install-project
- uses: gigaverse-app/ci-esta/actions/trivy-scan-image@v1
  with:
    # rootfs inventories installed .dist-info packages; fs is for manifests.
    scan-type: rootfs
    scan-ref: .venv
    vuln-type: library
    scanners: vuln
```

Use `skip-dirs` only for a documented inventory boundary (for example, a
package manager's bundled implementation dependencies that the product never
executes), not to suppress an actionable vulnerable application package.

When two inventories run sequentially in one job, the first invocation should
use the defaults. On the second, set `skip-setup-trivy: "true"` and
`cache: "false"`: Trivy is already on `$PATH`, and bypassing a second cache
restore preserves the freshly downloaded database in the shared cache directory
instead of restoring stale data over it.

Poetry follows the same contract: Poetry evaluates its lock, groups, Python
version, and platform markers; Trivy evaluates the resulting installed package
metadata. Keep the virtual environment in-project so the scan target is explicit
and does not depend on Poetry's global cache layout.

```yaml
- run: poetry install --all-groups --no-root
  env:
    POETRY_VIRTUALENVS_IN_PROJECT: "true"
- uses: gigaverse-app/ci-esta/actions/trivy-scan-image@v1
  with:
    scan-type: rootfs
    scan-ref: .venv
    vuln-type: library
    scanners: vuln
```

## `backend-common/reusable-semgrep.yaml`

Whole Semgrep job (runs in the `semgrep/semgrep` container, renders a job
summary, posts a PR comment). Calls `resolve-security-trigger` internally, so the
consumer stub only owns the `on:` triggers:

```yaml
name: Semgrep CE scan
on:
  pull_request: { types: [labeled] }
  issue_comment: { types: [created] }
  push: { branches: [main] }
  workflow_dispatch: {}
permissions: { contents: read, pull-requests: write }
jobs:
  semgrep:
    uses: gigaverse-app/backend-common/.github/workflows/reusable-semgrep.yaml@<pinned-sha>
    secrets: inherit
```

When a consumer also runs Trivy (or another security scan), resolve once in the
consumer and pass `decision-precomputed: true` plus `should-run`, `ref`, and
`pr-number`. The internal resolver job then skips and both scans remain parallel.

The scan preserves `always()` so a precomputed decision can bypass that skipped
resolver, but explicitly excludes cancelled callers. Consumer workflow
concurrency can therefore stop obsolete Semgrep containers instead of making a
new PR head wait for the old scan to finish.

Override the rule set per repo via the `configs` / `exclude` / `exclude-rules`
inputs; defaults match the gigaverse-ai baseline. Prefer
`extra-exclude-rules` when a consumer only needs to append a repo-specific
exception while continuing to inherit the shared exclusions.

## Why not also a reusable Trivy workflow?

The Semgrep scan is identical everywhere, so it ships as one workflow. Trivy's
**build** is not: `gigaverse-ai` builds N images from one parametrized
`deployment/Dockerfile` driven by a `.github/services/*.yaml` registry, while
`gigaverse-backend` builds a single image from `Dockerfile-backend`. Forcing both
into one workflow means conditional build inputs that leak each repo's layout.
Instead each repo keeps its own build/matrix and shares the two things that are
actually common: the trigger gate and the scan policy.

> This is backend-common's consumer policy, not CI-esta's versioning scheme.
> Consumers pin `PR<N>` while testing an open backend-common PR and immutable
> `v<N>` after it merges. The downstream bump workflow generates every
> backend-common reference from that one `pyproject.toml` revision (see
> `update_ci_esta.yaml`, `sync_backend_common_status.yaml`).

## `backend-common/reusable-ci-code-validation.yaml`

Runs Actionlint, composite-action metadata validation, ShellCheck, targeted
Semgrep, and Trivy configuration/secret scanning against changed files under
caller-provided CI roots. The caller owns only event path filters and the
newline-delimited roots:

```yaml
jobs:
  validate:
    uses: gigaverse-app/backend-common/.github/workflows/reusable-ci-code-validation.yaml@<consumer-ref>
    with:
      ci-paths: |
        .github
        scripts/ci
```

The planning job validates roots, ignores deleted files, and passes the exact
added/modified file set to every checker. On PRs it starts at the newest fresh,
successful ancestor from the same workflow and same PR whose named evidence job
actually succeeded; failed, cancelled, skipped, stale, unrelated, or
non-ancestor runs are never reused. GitHub's PR `paths`
filter is cumulative, so the planner may still allocate after a prior CI change,
but an empty new delta skips the Semgrep container plus the lint and Trivy
steps. No secrets are accepted or inherited.

Backend-common's own `ci-code-validation.yaml` also invokes each composite action
through a relative `./actions/...` reference. This is intentional:
consumer-facing calls stay pinned to known commits, while pull requests in this
repository exercise the implementation in the current checkout. Its reusable
call sets `run-checks: false`, reusing only the shared change plan so the same
files are not scanned once by pinned actions and again by local actions.

## `setup-python-uv`

Centralizes backend-common's Python version, uv installation, dependency cache,
and development dependency installation. It syncs with `--locked`, so a
`pyproject.toml` edit that is not accompanied by a refreshed `uv.lock` fails the
build instead of silently resolving something new. It is local project
setup rather than a consumer-facing contract. The repository's test workflow is
also intentionally local. Push and pull-request runs are allowed to overlap:
guaranteed pytest execution is more important than deduplicating CI events.

This extracted action caches uv downloads and runs `uv sync --locked --all-groups`.
It does **not** implement Backend's separate `.venv` restore/validation/save
composite. Review the [cache boundaries](../docs/ci-optimization.md#cache-the-right-thing)
before treating these similarly named actions as interchangeable.

### Distributed pytest ranges

`ci-esta-pytest run-local --shards N --first-shard A --last-shard B -- ...` runs the inclusive range A–B from one global exact-file plan. Workers retain global `GV_PYTEST_SHARD_INDEX` and `GV_PYTEST_SHARD_COUNT`; logs and completion reports therefore remain disjoint across machines. Omitted bounds preserve the existing all-shards behavior. Invalid or empty ranges fail before starting a worker.

Pass the same bounds as `PLAN_FIRST_SHARD` and `PLAN_LAST_SHARD` to `verify-pytest-completion`. Each pool proves its entire range. The consumer must require every pool, verify that its ranges partition 1–N, and issue the reusable aggregate receipt only after all pools prove completion. A successful pool alone never authorizes reuse of the global plan.
