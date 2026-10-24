# Closing the upstreaming gaps

## Adoption follow-up, 2026-10-24

The follow-up inspected default-branch workflows and local action implementations
for every repository found by organization and global code searches for both
toolkits. Nine repositories execute them. `deployment-plan` and `linear-git`
mention the tools without calling them in their own CI; the external
`szabgab/pydigger-data` match is package metadata, not a consumer integration.
Search indexes can lag, so this is a revision-bound inventory, not a claim about
all private or newly created installations.

| Consumer and inspected revision | Existing adoption | Decision from the review |
| --- | --- | --- |
| backend-common `2f1a0c773135b103a4c1e1a175282e48780bf4d5` | File selection before setup, reports, download caching, serial execution | Replace the copied checkpoint expression and shell splitting in [PR 286](https://github.com/gigaverse-app/backend-common/pull/286). Preserve manual selection. Its measured four-worker experiment was slower; additional sharding/history is deferred. |
| CI-esta `dd9a9bd951d4ceced03561501c9b693c5a6bb016` | Whole-lane selection, environment cache, completion receipts, reports, executable action smoke | Add the read-only `adoption` command, forward selector defaults/JSON paths and consume shared event policy. Keep optional retention off in its own fixed test matrix. |
| pytest-selective `cbf05c730af99229bf52b8c2c6afe5e0d531b219` | File and lane selection, cached setup, matrix/xdist, JUnit timing artifacts, reports | [PR 63](https://github.com/gigaverse-app/pytest-selective/pull/63) centralizes event policy and JSON outputs, removes local report parsing, and updates the tutorial/skill. Timing artifacts remain measurement inputs; changing its fixed matrix needs a measured benefit. |
| Due `55c07b3b8534cb6cb05d35a177d367779c1b9fd1` | Whole-lane selection, environment cache, whole-lane receipts, timing artifacts and reports | [PR 109](https://github.com/gigaverse-app/due/pull/109) uses shared event/base defaults in CI and widget comparison. Preserve complete conformance checks and service isolation; no speculative file sharding or retained-history opt-in. |
| pytest-obligation `3d137a57a340e677e3d33235921afae1183dd3ca` | Framework/service lanes, environment cache, matrix/xdist, timing artifacts and reports | [PR 135](https://github.com/gigaverse-app/pytest-obligation/pull/135) uses shared event policy, fixing the omitted rerun checkpoint. Correct stale docs that claimed main/prose always ran all tests. Keep external adopter and conformance boundaries intact. |
| gigaverse-ai `c21a8bdb7d212d390396a66a08b8ddd05006f210` | File selection, cached setup, frozen timing input across runner pools, completion checks, reports and opt-in retained history | [PR 3140](https://github.com/gigaverse-app/gigaverse-ai/pull/3140) is merged. The released 1.3.1 reader restored 22 file costs from a real main checkpoint. Preserve its explicit coverage policy and opt-out. |
| gigaverse-backend `e85f935c41c3df82f1bb727e9174b948333b1f88` | File selection, caches, local shard pools, completion/reuse checks, reports and retained observations through the shared Python library | [PR 5529](https://github.com/gigaverse-app/gigaverse-backend/pull/5529) is merged. Keep its existing persistence and coverage policy; absence of action `history-key` inputs does not mean library retention is absent. |
| gigaverse-mobile `bd9ee9cbbcc25b137123ff4a8ebd9d9f1ce01a31` | Bun inventory/selection/execution, raw evidence and completed-run reports | Keep the Bun-specific policy and existing private dependency setup. Python selection and pytest timing retention do not apply. |
| gigaverse-web-app `5efbceea35a9d8bebc9323af5218aea4e1136dba` | Bun selection, execution evidence, whole-lane receipts, aggregate gate and reporting | Keep the existing Bun executor and measured policy. Python-specific mechanisms do not apply. |

The main adoption gap was duplicated glue and incomplete guidance, rather than a
need to enable every optional action. Shared defaults now distinguish ordinary
PR/push selection from full checkpoints, and explicit overrides keep intentional
coverage/manual policies local. The new inventory command links suggestions to
source files and calls out opaque scripts/remote workflows. It cannot prove
successful runs or recommend more workers from static wiring alone.

Actions using a moving `v1` receive compatible implementation updates. Explicit
caller inputs still win. New workflows, retained-history keys, permissions,
Python lockfiles and installed agent skills do not appear automatically. Follow
the [adoption checklist](tutorials/adoption-checklist.md) to opt in deliberately.

## Original extraction closure

The [original audit](adoption-audit.md) distinguished extraction from adoption.
These changes close its generic implementation gaps without moving application
credentials, deployment policy or conformance contracts into the toolkit.

| Capability | Durable implementation | Adoption / evidence |
| --- | --- | --- |
| Real dependency critical path | [PR 15](https://github.com/gigaverse-app/ci-esta/pull/15), source-workflow DAG, observed chain, execution CPM, slack and delay | CLI exercised against real runs; observer enabled in all four projects |
| Validated complete uv environment cache | PR 15, exact interpreter/platform/manifests/groups identity, broken-restore repair, locked sync | CI-esta plus [selective 27](https://github.com/gigaverse-app/pytest-selective/pull/27), [obligation 103](https://github.com/gigaverse-app/pytest-obligation/pull/103), [Due 82](https://github.com/gigaverse-app/due/pull/82) |
| Strict selected-lane aggregate gate | [PR 16](https://github.com/gigaverse-app/ci-esta/pull/16), shared action and workflow contract checker | All four retain always-run package/metadata checks and full/unknown-input execution |
| Conservative PR supersession | First PR attempts share a cancellation group; main, manual and reruns remain isolated | All four main workflows; Due widget workflow too |
| Runner capacity and local pools | [PR 14](https://github.com/gigaverse-app/ci-esta/pull/14), bounded global shard ranges, resource diagnostics and watchdog | Backend recipes preserved; small projects retain appropriate xdist/service isolation |
| Timing feedback | [PR 20](https://github.com/gigaverse-app/ci-esta/pull/20), `ci-esta-pytest learn`, reusable JUnit artifact action | [Executable tutorial](learned-test-timings.md), real pytest-to-planner regression and 1,050-test local execution; [selective 29](https://github.com/gigaverse-app/pytest-selective/pull/29), [Due 85](https://github.com/gigaverse-app/due/pull/85), [obligation 104](https://github.com/gigaverse-app/pytest-obligation/pull/104) |
| Backend rollout | Shared toolkit consumers | [AI 3109](https://github.com/gigaverse-app/gigaverse-ai/pull/3109) and [Backend 5495](https://github.com/gigaverse-app/gigaverse-backend/pull/5495) merged |

The gate validates completion; reports remain outside its dependency chain.
The repository rulesets now require `Validation gate` on each default branch;
Due also requires `Widget comparison gate`, in addition to its existing checks.
Duration hints and cached environments cannot authorize successful-lane reuse.
Whole-file sharding is available, but adding hosted jobs to short suites can cost
more than it saves. Due's crash/conformance and widget evidence retain their
existing validators. Application fixtures and external service state cannot be
inferred from Python imports alone.

See [critical paths](critical-path.md), [environment caching](environment-cache.md),
[selected gates](selected-gates.md), [runner pools](runners-and-diagnostics.md),
and [agent instructions](agents.md) for adoption, failure controls and boundaries.
