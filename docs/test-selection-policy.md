# Select work from evidence, across Python and JavaScript

Keep ordinary PRs, pushes and their reruns selective. Run full checkpoints when
explicitly requested or when the inputs needed to select safely are unavailable.
A changed base commit alone is not a reason to run the full suite.

Start with the [adoption inventory](tutorials/adoption-checklist.md#1-record-a-useful-baseline),
then choose the adapter for the command the project actually executes:

| Test command | Selection owner | CI-esta responsibility |
| --- | --- | --- |
| pytest | pytest-selective dependency graph, file and complete-lane planners | Evidence, failure recovery, execution, timing and reports |
| bun test, including TypeScript/React projects | Bun's native import graph through `--changed` | [Bun adapter](bun-test-selection.md): complete inventory, global inputs, tested-tree proof and execution |
| Jest, Vitest, Playwright or another runner | That runner's supported selector or a repository-owned complete-lane declaration | [Portable evidence/reporting](non-python.md); never substitute Bun because the source is TypeScript |

The policy agrees across languages; discovery, dependency analysis and coverage
semantics stay with the real runner. Ordinary selected execution, a proven empty
selection and reuse of a completed job are three different outcomes.

## Choose scope before deciding whether to execute it again

1. Resolve the occasion and any explicit full request.
2. Select the required work from complete change evidence and declared inputs.
3. Optionally reuse a successful receipt for exactly that work and execution contract.
4. Execute everything still required, verify completion, then publish evidence.

A rerun disables receipt reuse but preserves selection. It can still select no
application tests for docs, while always-run contracts execute. GitHub reruns use
the saved triggering event: adding `test:full` later does not change that payload.
Use a fresh subscribed event or manual full dispatch when requesting a checkpoint.
Neither a cache hit nor a timing artifact proves tests passed. A subset must not
emit a receipt claiming the whole suite ran. A validated incremental baseline
may be established by a completed chain of selections anchored in full validation;
its completion marker must assert that contract and be versioned when it changes.

## Scenario map

| Scenario | Required behavior |
| --- | --- |
| Ordinary PR/push, including attempt 2+ | Select affected work; reruns execute it rather than reuse receipts |
| Manual, schedule, release, or reusable-workflow call with no explicit override | `full: auto` requests a full checkpoint |
| `test:full` in the saved PR event | Full checkpoint; do not reuse completion evidence |
| Explicit `full: true` / `false` | Override event policy; `false` still cannot bypass invalid history or policy |
| Unsupported/missing event metadata under `auto` | Full with an explicit fallback reason |
| Docs only, no runtime reader of the docs | Zero application tests; retain declared always-run contracts |
| Lock, setup, workflow, global input, opaque runtime dependency | Select every affected lane; Bun defaults these to its complete inventory |
| Whole-suite coverage floor or atomic conformance validator | Keep its complete lane; do not lower the floor to fit a subset |
| Same declared inputs and complete fresh receipt | Reuse only on eligible automatic events, within its freshness window |
| Main advances with unrelated docs | Compare tested trees; no forced checkpoint merely because the base SHA changed |
| Main changes a dependency or reverts an earlier change | Include that change in the tested-tree delta, even when PR-head delta is docs only |
| PR merges main | Python can choose the smaller of independently complete validated-head and PR-base plans; preserve unresolved failures in either |
| Prior pytest failure with complete shard/JUnit evidence | Add every unresolved failure file to the new selected work before advancing from the failed head |
| Partial/malformed failure artifacts | Retain the broader PR baseline; never treat missing failures as success |
| Newer contradictory failure or unverifiable ownership | Do not reach through it to an older success; use ordinary selection/fallback for the affected lane |
| Newer proven success, older uncertainty | Use the newer proof; older uncertainty does not force extra work |
| GitHub workflow index lag | Receipt lookup checks the head's check runs in completion order; generic validation mode retains fallback instead of walking past possible failures |
| Force-push, unrelated/recycled branch, expired proof | Reject incompatible history and re-establish the baseline |
| Missing historical merge, wrong merge parent, dirty/untracked inputs | Bun runs the full inventory and reports the specific reason |
| Fork PR | No same-repository receipt reuse; retain unprivileged validation and the repository's complete-input fallback |
| Push after merge or version-only release | Optional strict receipt modes only; ordinary pushes remain selective and publishing checks remain mandatory |

A fallback is scoped to the unavailable proof. Lane receipt uncertainty means
execute that lane's selected work. Python incremental uncertainty normally means
select from the complete PR diff. A workflow requiring a validated merged-tree
baseline must establish a full checkpoint when that baseline cannot be proven.
These are different contracts, not a universal command to run every job.

## Which Git identity was actually tested?

GitHub's PR head SHA and synthetic merge SHA can name different trees. Record the
identity used by the test checkout, and compare the old tested tree directly to
the new tested tree. Never reconstruct an old test result from today's main.

| Checkout | Historical identity | Safe comparison |
| --- | --- | --- |
| PR head | Proven successful PR head | Old tested head to current tested head; ancestor check |
| Synthetic merge | Exact merge recorded by the successful evidence job, plus its PR head | Old tested merge to current checkout; validate two parents, second parent equals proven head, proven head is an ancestor of current checkout |
| Complete lane receipt | Declared Git inputs, tool implementation and execution context | Match the receipt; no test-selection inference from the SHA alone |

Historical synthetic merges are siblings, so requiring one to be the other's
ancestor loses valid optimization. Conversely, substituting the old PR head for
the old tested merge loses base-branch changes and reverts. The Bun adapter's
`validated-head` input enables the parent proof; omit it for an ordinary ancestor
comparison. Saved plans revalidate the same proof before execution.

Git has current and past main commits, and Actions has runs on those commits.
Neither fact proves the PR passed against them. A main result is useful only when
its tested inputs and required execution contract apply to the requested work.
Do not pick whichever historical main SHA produces the smallest diff. Python's
alternate-base optimization combines independently complete change evidence;
copying only the “smaller wins” heuristic into merged-tree validation is unsound.

## Set up tested-merge selection

The [complete Bun workflow](../examples/bun-tests/workflow.yml) shows checkout,
read-only evidence discovery, exact historical-merge fetch, native execution,
completion markers and artifact upload. Supply your existing inventory command,
Bun version and repository policy. It starts with full validation when PR proof
is missing, then narrows subsequent changes without requiring a checkpoint for
every main update. An ordinary rerun can use a prior completed run as a selection
baseline, but cannot reuse that run's execution receipt.

The new `validated-head`, `tested-merge-step-prefix` and `full: auto` Bun contract
must be present in the reviewed action revision. During rollout, pin the reviewed commit from [CI-esta #117](https://github.com/gigaverse-app/ci-esta/pull/117); use `@v1` after it contains these inputs. Do not point a consumer
at an older release and assume unknown inputs are enforced.

The ownership marker binds a run to the PR when GitHub omits `pull_requests`.
The completion marker binds validated work. The tested-merge marker names its
actual tree. All are top-level workflow steps because the jobs API does not
expose inner composite steps. Publish completion only after the required work
and execution-inventory checks succeed. Keep required gates strict and reporting
outside their dependencies. See [receipt setup](evidence-reuse.md) for whole-lane
reuse; the Bun adapter itself does not issue a whole-suite receipt.

## What the earlier integrations taught us

These are inspected implementation histories, not claims that one recipe fits
all repositories:

| Source | Durable lesson retained here |
| --- | --- |
| [backend-common completion verification #211](https://github.com/gigaverse-app/backend-common/pull/211) | Verify completion using the pinned action implementation; a successful planner or partial shard set is insufficient |
| [backend-common bounded history lookup](https://github.com/gigaverse-app/backend-common/commit/27aed3591c9afeed763a013481b98617fa6ccccf) and [shared API reads](https://github.com/gigaverse-app/backend-common/commit/48b471ec728d69ba06766dede465a8f30dd7befd) | Stop outside the PR's history and cache raw reads within one invocation, while keeping each lane's verdict independent |
| [backend-common canary recovery](https://github.com/gigaverse-app/backend-common/commit/a8a2075fc6597d990344e78823ef72019ad1598d) | Stale, uncollectable failure files must fall through to authoritative validation rather than deadlock a retry |
| [AI testing workflow](https://github.com/gigaverse-app/gigaverse-ai/blob/9ca14aeeee33ed13c0a1e1de27f2c131717a7c38/.github/workflows/testing.yaml) and [backend workflow](https://github.com/gigaverse-app/gigaverse-backend/blob/16b18bc27e9ed9a5ba202f486b6a670cdcb4ddd9/.github/workflows/test.yaml) | Explicit PR-head checkout, complete changed-file evidence, unresolved-failure union and alternate-base selection |
| [Due shared-scope migration #119](https://github.com/gigaverse-app/due/pull/119) | Bind the actual library/integration/matrix scope to receipts while retaining atomic conformance validators |
| [Web tested-merge review #4267](https://github.com/gigaverse-app/gigaverse-web-app/pull/4267) | PR-head history alone cannot describe a suite tested on synthetic merges; main reverts need the old tested tree |

AI/backend consumed the earlier backend-common mechanisms. Due's later adoption
helps establish portable lane/scope contracts; Due's application-level delivery
receipts are a different domain from CI completion receipts. Preserve that boundary.
Older adoption commits describe full reruns; the current event policy supersedes
that behavior. Historical PR prose is evidence of the migration, not current API
documentation.

## Enforcement and regression controls

| Invariant | Enforcement | Control |
| --- | --- | --- |
| Same event policy in Python and Bun | pytest-selective checkpoint API; Node-only `checkpoint.mjs` adapter | `tests/ci/test_checkpoint_parity.py` executes both on identical event payloads and attempts |
| No older green beyond uncertain newer ownership | Chronological candidate barrier in `resolve.cjs` | `test_unverified_owner_cannot_hide_newer_validation`, all three proof modes, newer/older controls |
| Index fallback respects newer failures | Paginated check runs, fetched run chronology and ownership barrier | `test_check_index_lag_obeys_chronology_and_ownership`, both API orders |
| Actual tested merge controls selection | `planAffectedTests` parent/ancestry checks and executor revalidation | Real Git/Bun main-revert failure and docs-only controls in `bun-selection.test.mjs` |
| Requested work and actual execution stay separate | Shared Bun completeness predicate fails execution before a receipt can be published; strict gates | Real Bun execution with damaged timing evidence fails; pytest completion and lane-gate controls |

Run `uv run pytest -q tests/ci/test_checkpoint_parity.py tests/ci/test_incremental_evidence.py`
and, with Bun >=1.4.2 <2 and Node 22+, `node --test tests/github_actions/bun-selection.test.mjs`.
The cross-runtime test uses the installed supported pytest-selective package;
production Bun jobs do not install Python. Hosted public-action smoke exercises
the actual composite boundary. Measure same-source full/selected controls,
required-gate elapsed time, summed runner time and observer overhead separately.
Correct selection does not itself establish a measured speedup.
