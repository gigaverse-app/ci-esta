# Test execution policy: impact, occasions, resources and evidence

Status: proposed public API in CI-esta PR #98. **Do not merge until Aviad has reviewed this design.** Consumer PRs pin an immutable commit from this PR and remain open during review.

## Problem and decision

Affected-test selection answers which tests a change might reach. It does not decide whether this run should spend provider credits, occupy a shared broadcast slot, execute a large benchmark, or probe a deployment even when no code changed.

Add a small policy planner between impact selection and provisioning. Accept an inventory of atomic work units, the existing selector's affected scope, a named profile and trusted run context. Return explicit run, unaffected, deferred and unavailable decisions. Keep test commands, credentials, infrastructure lifecycle and required completion gates in the project.

The implementation is Python, but its JSON contracts and Actions work with any test runner. A Bun or Playwright project does not install pytest or change its application dependency manager. A Python project may call the same typed API directly.

## What the source repositories contributed

| Source, inspected base | Useful behavior | Generalized boundary | Project ownership retained |
|---|---|---|---|
| AI, `d9814b9a3` | Test-owned requirements, ordered providers, exact pins, runner/Kubernetes placement, per-node filtering | Resource models/resolution; boolean marker metadata adapter; explicit lane profiles | Registry, settings discovery, pytest collection hooks, image/job lifecycle, slash-command authorization |
| Due, `262a6d3` | Whole-suite selection, validators after tests, large benchmark/profile matrix | Atomic work IDs and complete suite admission | Django variants, conformance reports and validators, baseline/candidate benchmark comparison |
| Backend, `262e5ce36` | Independent service lanes, manual probes, immutable deployed-image checks | Occasion and environment constraints, fresh manual/deployment work | Image provenance, deployment readiness, production confirmation, namespace and database lifecycle |
| Web, `5efbceea3` | Native Bun impact selection, mock/live separation, elapsed-time budgets, serialized shared accounts, deployed build identity | Language-neutral inventory, effect permissions, freshness, remaining-budget helper/action | Bun selector, Playwright execution, distributed serialization, account ownership, readiness polling |
| CI-esta, `5b8fb5a` | Conservative reuse, execution receipts after validation, mandatory gates, work reports | Policy composes with existing evidence and gate actions | Evidence identity, expiry and terminal-result checks remain in their existing APIs |

The source map is about behavior, not exporting every source file. A repository-specific image launcher or account provisioner would be a poor shared default. In particular, AI's old YAML fields `blocking_initially`, `requires_manual_request` and `requires_isolated_destinations` were declarations without general enforcement. They are not advertised here as an existing security mechanism.

## Opinionated defaults, with exceptions

A new adopter needs work IDs, not a copied profile catalog. The Actions default to
`ci`; a policy file is optional. CI-esta owns the versioned `v1` profile set:

| Profile | Default scope and eligibility | Occasions |
|---|---|---|
| `ci` | Affected work; excludes `expensive` and `manual` tags | PR, push |
| `thorough` | All ordinary work; excludes `expensive` and `manual`; fresh | Manual, schedule |
| `full`, `deep`, `exhaustive` | Same full checkpoint; includes expensive, excludes manual; fresh | PR, manual, schedule |
| `weekly` | Full checkpoint; includes expensive, excludes manual; fresh | Schedule, manual |
| `smoke` | Work ID or tag `smoke`; excludes manual; fresh | Push, manual, deployment |
| `performance` | Work ID or tag `performance`; excludes manual; fresh | Manual, schedule |
| `probe` | Explicit requested work only; fresh | Manual |
| `legacy` | Pass through affected scope, including expensive/manual tags | All normalized occasions |

**No built-in grants side effects.** A full/weekly run still defers a paid or
visible-output test unless a project explicitly allows its declared effects.
A `manual` tag therefore means deliberate probe-only by default; a custom profile
can provide an intentional exception. Unknown impact broadens only eligible work.
Work IDs also match includes/excludes, so `smoke` does not need a duplicate tag.

```yaml
# Zero policy file. Existing default-branch/manual routing can choose legacy
# explicitly during migration; new adopters start with ci.
- uses: gigaverse-app/ci-esta/actions/plan-test-policy@<reviewed-commit>
  with:
    work: '["unit", {"id":"benchmark", "tags":["expensive", "performance"]}]'
    affected: ${{ steps.select.outputs.lanes }}
    # occasion defaults to github.event_name and is normalized by CI-esta
```

For an existing selector, use `lanes: .github/test-lanes.json` (JSON or YAML) to
reuse its `lanes` keys. CI-esta reads only the inventory, not its dependency graph.
An optional policy `work` list then contains metadata **only for exceptional IDs**.
Unknown metadata IDs fail instead of silently creating another lane registry.
Alternatively, `work` is inline JSON and `inventory` is a complete adapter-generated
file. Choose one inventory source. Missing inventory fails; explicitly empty
inventory remains representable.

```yaml
# Only the project-specific exceptions, not a copied weekly profile.
profiles:
  weekly:
    allow_effects: [provider-spend]
  production-probe:
    extends: probe
    environments: [production]
    require_deployment: true
work:
  - id: provider-eval
    tags: [expensive]
    effects: [provider-spend]
```

Named built-ins inherit automatically. Other names use `extends` or supply a
complete standalone `occasions`/`include` definition. Explicit fields replace
inherited fields, including arrays: `allow_effects: []` removes grants. Unknown
fields/parents and inheritance cycles fail. Defaults resolve once before planning;
there is no second runtime merge. `defaults: none` disables the catalog entirely.
The pin selects the implementation; `defaults: v1` identifies the behavior family.
Changing its defaults requires parity tests and visible release notes.

The four migrations keep their existing workflow input default `legacy`. This
preserves current execution while offering the common defaults for new setups.
BE deletes its ordinary policy file; web deletes its mock policy file. Due keeps
one benchmark classification and a PR-occasion exception for `thorough`. AI keeps
its affected-only `deep` exception, effect grants and exceptional lane metadata.
Backend operational and web live policies keep their real environment/effect
exceptions. Per-project fixtures remain local because they prove project wiring.

## Before and after

```text
BEFORE
 AI:   impact + labels + markers ---> local resource resolver ---> pytest/cluster
 Due:  impact + workflow conditions -----------------------------> suites + validators
 BE:   impact + manual/event conditions -------------------------> unit/services/drills
 Web:  native impact + event conditions + local budget math ------> Bun/Playwright
                  each workflow interprets its own occasion rules

AFTER
                 trusted event / authorized request
                              |
 native impact selector ------+------ inventory + project policy
 (pytest-selective, Bun,       |
  path rules, or unknown)      v
                    plan-test-policy
                    /       |       \
              unaffected deferred unavailable ---> planning failure retained by gate
                              |
                             run
                              |
                 optional resource resolution
                 /            |             \
              local       service container   cluster
                              |
                 existing executor + validators
                 |      test-budget at launch
                 |      existing concurrency / leases
                 v
             validation-gate ---> execution evidence ---> reports
```

Policy admission is not successful execution. A provider being resolvable is not proof that the service is healthy. A declared environment is not proof that a revision is deployed.

## Actions and their relationships

| Action/API | Input | Output / responsibility |
|---|---|---|
| pytest-selective `plan-lanes`, CI-esta `test-impact`, or native selector | Git tree pair and declared dependencies | Affected IDs or complete lane-to-boolean map; remains authoritative for impact |
| **`actions/plan-test-policy`** | Policy, profile, occasion, revision, affected/requested IDs, optional environment/readiness identity | Complete admitted/fresh maps, count and versioned decision plan; no commands or provisioning |
| **`actions/check-test-policy`** | Policy and project-owned routing examples | Tests the installed CLI from the exact action revision; fails on wrong routing or expected failures |
| **Resource Python API / `python -m ci_esta.policy.resource_cli`** | Provider registry, requirements, available credential names, target environment | Per-work placement or unavailable reasons; no credential values required |
| Existing `service-container`, `setup-cached-uv`, image and project setup actions | Admitted work and project-owned configuration | Provisioning; policy does not duplicate these implementations |
| **`actions/test-budget`** | Job start, total/requested seconds, cleanup reserve | Positive remaining seconds for the native runner timeout; fails when exhausted |
| Existing `resolve-lane-evidence` / `resolve-pytest-evidence` | Admitted scope and evidence identity | Reuse only when freshness permits and all existing proof requirements pass |
| Existing `validation-gate` | Mandatory planner/executor outcomes and admitted requirements | Missing, failed, cancelled or unexpectedly skipped work cannot pass |
| Existing reporting actions | Actual plan, execution and timing evidence | Explain work and outcomes without making reporting a prerequisite of validation |

```text
impact ------> policy ------> reusable? ------> matching prior proof
                 |             |
                 |             +-- fresh / no proof --> executor --> validators --> receipt
                 +-- error -----------------------------------------------> required gate fails
```

For Due, a work ID such as `integration` covers its tests **and** application validators. The profile does not split out a validator as an optional unit. For web, the mock harness remains a separate workflow from live-account tests. Backend's required unit-plan artifact retains its existing lifecycle.

## Public schemas

Schemas are generated from the runtime models, committed under `docs/schemas/test-policy/`, and checked against those models in tests. Regenerate with:

```sh
python -m ci_esta.policy.schemas docs/schemas/test-policy
```

| Schema file | Contract |
|---|---|
| `policy.schema.json` | `ci-esta/test-policy/v1`, named profiles and optional static work inventory |
| `request.schema.json` | `ci-esta/test-request/v1`, normalized context and affected/requested IDs |
| `inventory.schema.json` | Array of work units; adapters can generate these from test metadata |
| `plan.schema.json` | `ci-esta/test-plan/v1`, request, complete decisions, fallback and budget declarations |
| `resource-registry.schema.json` | Resource name to ordered provider definitions |
| `requirements.schema.json` | Work ID to required resource/provider/capability declarations |
| `resource-plan.schema.json` | `ci-esta/test-resources/v1`, resolved placements or unavailable reasons |

Policy/request/work models reject unknown fields. Policy adds `defaults` (`v1` or `none`); `profiles` is optional and contains only overrides or custom definitions. The JSON schema specifies fields; the versioned catalog and inheritance rules above supply the default policy semantics. Core fields are:

| Object | Fields and meaning |
|---|---|
| Work | `id`, `tags`, `effects`, optional `environment`, `fresh`, `timeout_seconds` |
| Profile | optional `extends`, `occasions`, `include`/`exclude` tags or IDs, `scope` (`affected`, `all`, `explicit`), `allow_effects`, allowed `environments`, `require_deployment`, `fresh`, optional `budget_seconds` and `reserve_seconds` |
| Request | `profile`, `occasion` (`pr`, `push`, `schedule`, `deployment`, `manual`), `revision`, optional `environment`, `deployed_revision`, `affected`, `requested` |
| Decision | Full work declaration, `status`, human-readable `reason`, effective `fresh`, optional command timeout ceiling |
| Requirement | `resource`, optional exact `provider`, required `capabilities` |
| Resource | `name` and providers in preference order |
| Provider | Name/capabilities, runner and cluster credential references, static runtime environment, optional service container, environment scope, optional Kubernetes job profile |

IDs and tags are data. The policy has no shell command field. Requested profile names do not grant GitHub permissions.

### Admission rules

1. Validate the profile, occasion, unique inventory and requested/affected IDs. Unknown profiles, unknown explicit targets and empty explicit requests fail.
2. Exclude matching work tags/IDs, then include matching tags/IDs, subject to the effect ceiling. `include: ["*"]` does not override effects.
3. `affected` scope intersects eligible work with impact. `null` means unknown, so it broadens to eligible work. `[]` means known empty. A partial boolean map is an error, not proof that omitted IDs are unaffected.
4. `all` ignores impact. `explicit` requires requested IDs. Explicit requested IDs narrow scope and bypass impact, but cannot bypass profile or effect restrictions.
5. Admitted work must match its required environment and profile environment allowlist. `require_deployment` also requires an environment and observed deployed revision equal to the requested revision. Missing/mismatched prerequisites produce `unavailable`, not a successful skip.
6. Manual, scheduled and deployment occasions are fresh. Work/profile freshness can additionally forbid reuse on a PR. The consumer must honor the returned freshness before invoking evidence reuse.
7. A profile budget caps each admitted command at total minus reserve. It is not a global parallel scheduler. At execution time `test-budget` additionally subtracts elapsed setup time. The native runner must enforce the result.

The planner emits an artifact for unavailable work and returns nonzero. Invalid input removes any previous plan at that output path. Executors must require planning success; consuming an artifact from a failed invocation is incorrect. External admission failures may retain an existing conservative ordinary-test fallback, but must never become permission to run restricted probes.

## Useful setup: ordinary CI and special occasions

See `examples/test-policy/policy.json` for an executable version of this setup:

```yaml
schema_version: ci-esta/test-policy/v1
profiles:
  pr:
    occasions: [pr, push]
    include: [unit, integration]
  weekly:
    occasions: [schedule, manual]
    include: [unit, integration, paid]
    allow_effects: [provider-spend]
    scope: all
    fresh: true
  probe:
    occasions: [manual]
    include: ['*']
    allow_effects: [provider-spend, visible-output]
    scope: explicit
work:
  - {id: unit, tags: [unit]}
  - {id: conformance, tags: [integration]}
  - {id: provider-eval, tags: [paid], effects: [provider-spend]}
  - {id: publish-smoke, tags: [live], effects: [visible-output]}
```

```sh
# Existing impact selection, including non-Python selectors:
ci-esta-test-policy --policy examples/test-policy/policy.json --profile pr \
  --occasion pr --revision "$HEAD_SHA" --affected '["unit","provider-eval"]'
# Only unit is admitted. Impact did not grant permission to spend.

# Same code, fresh weekly validation, including the explicitly permitted paid suite:
ci-esta-test-policy --policy examples/test-policy/policy.json --profile weekly \
  --occasion schedule --revision "$HEAD_SHA" --affected '[]'

# An authorized human/agent probes one visible-output test:
ci-esta-test-policy --policy examples/test-policy/policy.json --profile probe \
  --occasion manual --revision "$HEAD_SHA" --requested '["publish-smoke"]'
```

GitHub integration passes the existing selector's output directly:

```yaml
- id: policy
  uses: gigaverse-app/ci-esta/actions/plan-test-policy@<reviewed-commit>
  with:
    policy: .github/test-policy.json
    profile: ${{ inputs.profile || 'legacy' }}
    occasion: ${{ github.event_name == 'pull_request' && 'pr' || 'manual' }}
    affected: ${{ steps.select.outputs.lanes }}
```

Normalize every actual trigger in a real workflow; the small example above covers PR/manual only. Map an authorized label to a fixed configured profile; do not treat arbitrary comment text as a profile or command. Retain same-repository, collaborator and environment checks before handling credentialed requests. Schedule events should use an explicit complete profile when periodic validation is the intent.

## Resources: needed, optional, and separate from occasion policy

Resource declarations are useful when tests differ in prerequisites or placement. They are unnecessary duplication for a project whose whole suite always uses the same fixed services. Due and backend keep their existing static service jobs; AI adopts the resolver because individual tests already declare requirements.

```text
policy:    MAY this test run on this occasion?
resource:  WHAT could satisfy its declared prerequisites?
executor:  START / CHECK / STOP those prerequisites and run the test
```

Example: a Lua test requires Redis capability `lua`. A fake provider is first in the preference list but lacks that capability. Resolution selects the real disposable Redis provider. If the test pins a missing or incapable provider, resolution fails instead of substituting a fake.

```json
{"redis":{"name":"redis","providers":[
  {"name":"fake"},
  {"name":"ephemeral","capabilities":["lua"],"service_container":
    {"service_name":"redis","image":"redis:7-alpine","ports":["6379:6379"]}}
]}}
```

```json
{"redis-lua-tests":[{"resource":"redis","capabilities":["lua"]}]}
```

```sh
python -m ci_esta.policy.resource_cli \
  --registry examples/test-policy/resources.json \
  --requirements examples/test-policy/requirements.json --environment dev
```

The API preserves provider preference order, exact pins, environment restrictions, deduplication and collision errors. Runner containers cannot satisfy cluster-mode work. Cluster resolution assumes the target executor supplies declared configuration; it does not verify Kubernetes secrets or health. AI retains its existing two-pass placement and strict runtime checks. Collision diagnostics identify names without printing conflicting environment values or container credentials.

CPU, memory, worker counts and Kubernetes requests/limits are **execution capacity**, a separate concern from prerequisite providers. Keep these in executor configuration and benchmark them with CI-esta's existing resource observability. Do not put a universal CPU-to-test-cost formula in profile admission. Kubernetes timeout/service identity is carried by the existing placement contract; cloud account setup, autoscaling and resource quotas remain project-owned.

Shared accounts and broadcast slots need actual concurrency groups or leases. A planner cannot acquire a cross-job/distributed lock. Web keeps its existing serialized concurrency groups, including `cancel-in-progress: false` for live work, and its cleanup. There is deliberately no inert `exclusive` flag pretending that declaring a lock acquires one. Similarly, conformance validators remain part of the atomic executor job, rather than inert names in a generic policy file.

## Python-specific versus cross-language

| Cross-language boundary | Python-specific adapter |
|---|---|
| Versioned JSON policy/request/plan; CLI and Actions | Pydantic implementation and direct Python API |
| Suite/test IDs, tags, effects, environment, freshness, budgets | Pytest node IDs and marker metadata |
| Resource/provider/capability and placement JSON | AI pytest `requires` collection and runtime hook integration |
| Existing native impact selection | pytest-selective's Python dependency graph |

`ci_esta.policy.pytest_metadata.marker_expr_matches` extracts AI's existing restricted boolean marker evaluator. It supports names, `and`, `or`, `not`, parentheses and boolean constants; it does not claim full pytest keyword-argument marker syntax. It imports no pytest. The generic planner never interprets Python markers.

## Consumer rollout and compatibility

Each consumer starts with a separate behavior-preserving extraction commit. A later consolidation replaces copied profiles with shared defaults, retaining the same routing fixtures. `legacy` is the shared migration profile; project-owned exceptions preserve existing effect permissions.

| Repository | Preserved | New explicit paths |
|---|---|---|
| AI | No automatic PR provider spending; existing labels/commands, main merge lanes, exact pins, cheap probe | Deep affected lanes, full weekly checkpoint, smoke and explicit probe |
| Due | Current library/integration/type/contracts/wheel and widget selection, attached conformance validators, matrix and gates | Thorough conformance, exhaustive including comparisons, performance-only dispatch |
| Backend | Unit artifact lifecycle, path-selected independent services, manual-only operational jobs and provenance | Deep unit/integration validation; named operational smoke/stress admission |
| Web | Native selectors, mock authorization, live concurrency, deployment observation, active/disabled workflow state | Complete mock journeys, manual live smoke/full routing and shared elapsed budget |

Profiles do not automatically activate a new paid cron, enable disabled workflows or deploy anything. Existing schedules continue their existing work. A weekly profile can be dispatched immediately; changing an automatic schedule is a separately visible workflow edit. Labels are mapped where the consumer subscribes to label events; a label on its own does not make GitHub emit an event to an unsubscribed workflow.

All new consumers pin this PR's exact commit for review. Before release adoption, update them to the reviewed release or immutable reviewed revision and rerun their routing tests. Merge order is CI-esta review, CI-esta merge/release, then consumer repins/merges. Rollback is the consumer adoption commit; no service or test data migration is involved.

## Alternatives and scope

[pytest-optional-tests](https://github.com/reece/pytest-optional-tests) provides named optional test groups. Pytest's [markers](https://docs.pytest.org/en/stable/how-to/mark.html) provide useful metadata and selection. Those are sufficient when the problem is only opting into Python tests. This layer adds portable occasion admission between an existing selector and existing executors, plus resource placement and evidence freshness.

[Bazel](https://bazel.build/reference/test-encyclopedia) already defines a substantial test environment and execution contract. A project already using that ecosystem should reuse it. CI-esta targets repositories keeping pytest/Bun/Playwright and GitHub Actions rather than adopting a new build graph.

[GitHub concurrency](https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/control-workflow-concurrency) remains the mechanism for workflow/job serialization. Resource declarations complement that mechanism; they do not replace its lock behavior.

## Validation and limits

Tests exercise the public CLI, the actual composite-action shell, admission and effect boundaries, unknown versus empty scope, explicit requests, deployment identity, budget exhaustion, resource capabilities/pins/collisions, generated schemas, and consumer routing examples. AI additionally runs its existing provider/placement tests and new actual-selector profile cases. Existing repository tests continue to exercise native impact selection and gates.

CI-esta's Python 3.11/3.14 suites and installed-wheel smoke protect portability. The public-action smoke must exercise the new action from the PR checkout. Consumer contract actions install the same immutable source revision as their planners. No live operational probe needs to be dispatched merely to prove routing.

No CI savings are claimed by this extraction. Additional planner startup has a cost; static consumers gain consistent policy and auditable special-occasion execution, while AI removes duplicated resolver code. Measure cost separately before claiming optimization.
