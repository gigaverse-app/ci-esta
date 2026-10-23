# Upstreaming and adoption audit, 2026-10-23

This is the original snapshot. Follow-up implementation is tracked in
[the closure ledger](upstream-closure.md); the tables below preserve what was
missing at the audited revisions.

**The backend-common extraction is substantial, but upstreaming and adoption
are not complete across all seven repositories.** A copied implementation, a
shipped action, a configured caller and a successful live run are different
levels of evidence. Do not describe one as another.

This audit read the committed default-branch workflows, action implementations,
dependency pins, extraction inventory and documentation at these revisions:

| Repository | Audited revision |
| --- | --- |
| backend-common | `aa9ca1c36b06116816fb2c5f21087174c9575764` |
| gigaverse-ai | `1466f726a138d773e6c8afabf6e8c076525c8925` |
| gigaverse-backend | `33648b198dc880339f0bf3c8c9f5e60042146b14` |
| ci-esta | `34756458748ae3afd58c084ce4cee9c6880e8a5b` |
| pytest-selective | `43400aaa61d1348f54233782768e28d3933531e1` |
| due | `dc1763d220d0ac90b90a9504a1006b4e9142593c` |
| pytest-obligation | `03cf413c0592dba206d0652ed20c56fe1baf8d2a` |

Resolve a path against the revision above when reproducing this audit. Later
merges can change the result. This is a source/adoption audit, not a new speedup
benchmark or an exhaustive performance profile of application code.

## What is durable upstream

| Capability | Canonical implementation and evidence | Remaining boundary |
| --- | --- | --- |
| Python import graph, affected files, whole lanes, explanations | pytest-selective; real-Git selection/routing regressions and cross-platform CI | Runtime data, subprocesses and external checkouts require declared inputs |
| Graph caching and duration-based shard planning | pytest-selective `test-impact`, `plan-lanes`, planner; CI-esta delegates | Timing collection, persistence and execution must be wired by callers |
| Successful-lane receipts, incremental bases, stale-head admission, aggregate gates | CI-esta actions and actual JavaScript/API-boundary tests | Complete input contracts and event policy remain consumer responsibilities |
| Concurrent local shard pools, exact completion, JUnit/duration aggregation, coverage checks, failure canaries | CI-esta `testing/` and composite actions | A selected shard plan alone does not prove every shard executed |
| Job/step timings, all-attempt runner accounting, overlap, Markdown/JSON/Prometheus, Gantt | CI-esta `ci_observability/`; completed-run observer | No automatic causal critical-path computation |
| Security scan primitives, CI-code diagnostics, image identity reuse and measurement | CI-esta action catalog, `image_evidence/`, drill tooling | Deployment/authentication/inventory policy is not generic |
| pytest scope/isolation guards | pytest-selective; CI-esta aliases/delegates | Adoption in a repository is separate from owning the implementation |

The [inventory](migration-inventory.json) records 47 Python entries, 27 action
entries, 35 test entries, 33 script entries and two extracted workflow primitives
from backend-common revision `0f050d97d1e2d70514c653c742122d7b67b8aa55`.
Those are inventory entries, not counts of independently proven capabilities.
The [preservation ledger](migration-test-plan.md) records behavioral tests and
wheel installation checks. It is historical evidence; pending statements there
must be reconciled with later merges rather than treated as current status.

## Actual public-project adoption

| Capability | Due | pytest-obligation | pytest-selective | CI-esta |
| --- | --- | --- | --- | --- |
| Skip unaffected whole lanes | Yes, including widget lane | Yes, framework/service lanes | Yes, test matrix | Receipt reuse, not dependency-based lane selection |
| Always-run docs/package validation | Routing/docs contracts, lint/build | Routing/docs contracts, lint/build | Quality/routing/build | README is a test/build input; docs excluded from receipt inputs |
| Dependency download cache | Explicit setup-uv cache | Explicit setup-uv cache | setup-uv | setup-uv |
| Parallel work | Dependency matrix; widget matrix | Framework lanes; some xdist | OS/Python matrix and xdist | Two Python jobs and xdist |
| Learned duration cache + balanced CI shard pools | Not wired | Not wired | Not wired in own CI | Not wired in own CI |
| Completed-run CI-esta report | CI and widgets | CI | CI | CI |
| Required-gate timing configuration | CI gate list; widgets empty | Empty | Explicit job list | Explicit aggregate gate |
| Positive whole-lane receipt reuse | Not wired | Not wired | Not wired | Yes |

This table describes checked-in workflow wiring, not cache hit rates or a reason
to enable every mechanism. A small suite can get slower when split across more
runners. Whole-lane selection deliberately preserves complete conformance runs.

The public selectors pin `99f9af2bbe92534074657664903a1ce03bdeb44f` in the
consumer lane actions; the external reporters pin CI-esta
`3be6e84b86a36b9018798c2806a291f17fd077bf`. The lane action uploads a
`test-lane-selection` artifact and the reporter can consume it. CI-esta's own
observer calls its local reusable workflow. These are actual call sites, not
README endorsements.

Recent completed reporting examples include
[CI-esta observer 39856928007](https://github.com/gigaverse-app/ci-esta/actions/runs/39856928007)
and [Due observer 39856883411](https://github.com/gigaverse-app/due/actions/runs/39856883411).
Their success proves the observer ran; it does not prove all optional sections
were populated or establish a new comparative performance result.

## Gaps and acceptance criteria

1. **AI/Backend rollout is still open.** backend-common PR269 is merged, but
   both application default branches still pin v268. Their generated adoption
   PRs [AI#3109](https://github.com/gigaverse-app/gigaverse-ai/pull/3109) and
   [Backend#5495](https://github.com/gigaverse-app/gigaverse-backend/pull/5495)
   remain open at the snapshot. Passing bump checks are useful evidence, not a
   merged rollout. Completion means reviewed merged pins and successful consumer
   runs against those exact pins.
2. **Environment caches are not fully extracted.** Backend's
   `actions/setup-python-uv/action.yml` restores and validates `.venv`,
   keys it by resolved Python patch plus manifests, and supports trusted saves.
   AI has its own restore/save steps in `.github/workflows/testing.yaml`.
   CI-esta's similarly named action only installs Python/uv, caches downloads and
   syncs all groups. A portable environment-cache action needs explicit platform,
   interpreter, dependency-group, workspace and installation contracts, plus
   miss/stale/broken-cache tests. Private Git authentication stays caller-owned.
3. **A Gantt is not a causal critical path.** The renderer draws observed job
   intervals and highlights required gates. It exports direct prerequisites when
   supplied but explicitly does not reconstruct a transitive DAG. Computing
   critical paths needs complete dependency edges, matrix/reusable-job expansion,
   handling skipped/failed jobs, and separation of queue delay from execution.
   A long or red bar alone does not prove optimizing it will shorten merge time.
4. **Gate timing is incomplete.** Obligation and Due's widget observer supply
   no gate selectors. Selective and Due CI list some conditionally skipped jobs;
   the current renderer requires every listed gate to conclude `success` and
   labels a listed `skipped` gate as blocked, even after intentional routing.
   This is a reporting mismatch, not proof that validation failed. Completion means an
   always-reporting aggregate gate with explicit selected/skipped prerequisites,
   and live full, docs-only, failure and cancelled-run controls.
5. **Timing feedback is not adopted by the four public suites.** AI/Backend
   restore learned durations and run planned pools; the four public projects
   mostly use matrices/xdist. Measure first. If test execution dominates, retain
   per-shard durations/JUnit, merge only complete artifacts, warm a trusted cache,
   and validate complete partitioning before claiming balanced-shard adoption.
6. **Cancellation policies differ.** Due and obligation cancel by workflow/ref,
   including main; selective cancels PRs; CI-esta has stale-head admission but
   no workflow concurrency block at this snapshot. Preserve needed full baseline
   runs and prevent stale manual reruns from cancelling the current head. Test
   both overlapping pushes and manual reruns before standardizing policy.
7. **The shared observer blocks optional file reports.** At the snapshot,
   `report.yml` hard-codes empty file-explanation/reference inputs even though the
   action supports them. The audit follow-up exposes opt-in passthrough inputs
   while preserving empty defaults. File explanations still require
   `post-sticky: true` in the current action. Lane reports already work.
8. **Documentation had extraction residue.** The action catalog sent users to
   backend-common action paths and a nonexistent local observability page. The
   audit follow-up corrects those links and distinguishes retained workflow
   policy from public actions. The [optimization guide](ci-optimization.md)
   covers the missing cache/timing/parallelism adoption sequence.

Application-specific schema/database dumps, service startup choices, Docker
layers, runner sizing and build/test overlap remain in consumer workflows.
Extract common mechanisms after measuring them; do not copy private credentials,
environment assumptions or service policy into a generic toolkit. Backend's
measured shard-count comments and AI's pool topology are examples to investigate,
not universal default settings.

## What the existing performance claims establish

The [paired selection experiments](https://github.com/gigaverse-app/pytest-selective/blob/main/docs/benchmarks/2026-10-22-routing.md)
show scenario-specific savings, including 627 to 48 runner-seconds for one
pytest-selective README change. The [CI-esta report](benchmarks/2026-10-22.md)
measures a 279-second Windows job and 295-second gate elapsed time, with a
19-runner-second observer. Neither result proves complete extraction, universal
speedups, causal critical-path analysis, or savings from receipt reuse.
