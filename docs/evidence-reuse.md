# Reuse successful GitHub Actions jobs safely

See the [selection and evidence policy](test-selection-policy.md) for the scenario map, tested Git identities, reruns and Python/JavaScript setup.

A skipped job is not proof that its work passed. CI-esta reuses a lane only when a prior successful job carries a matching completion receipt. The receipt binds the tested inputs and the downloaded CI-esta implementation. An unavailable API or uncertain proof runs more work.

## Start with the whole tree

Use `gigaverse-app/ci-esta/actions/resolve-lane-evidence@v1` with a `lanes` JSON map of output keys to exact job names. Omitting `input-paths` binds the merged tree, base commit, and head tree. Recreated merge commits can match; changed inputs cannot.

Record the returned `receipt` as the name of a final successful step in each lane. It must run only after every required check succeeds. Never use `if: always()` or `continue-on-error` on that completion step. A planner's success is not a test result.

```yaml
# In your existing planner, after checkout:
- uses: gigaverse-app/ci-esta/actions/resolve-lane-evidence@v1
  id: evidence
  with:
    lanes: '{"tests":"Tests"}'

# In the Tests job, after all tests and required checks:
- name: ${{ needs.plan.outputs.receipt || 'Uncached validation completed' }}
  run: 'true'
```

Forward `steps.evidence.outputs.receipt` and `steps.evidence.outputs.reused` as planner job outputs. Admit the test job with:

```yaml
if: ${{ !cancelled() && (needs.plan.result != 'success' || !fromJSON(needs.plan.outputs.reused || '{}').tests) }}
```

The planner-failure branch is essential: missing evidence runs tests. Use the [complete dogfood workflow](../.github/workflows/ci.yml) as a working example of outputs, admission, receipts and an aggregate gate.

## Declared execution inputs

When one job conditionally runs different sets of work, pass that selection as
`execution-context`. For example, a Django job that runs library tests, integration
tests, or both can pass the normalized JSON `{"library":true,"integration":false}`.
An identical Git tree alone does not establish that the same tests ran. Context
values are compared exactly; produce them deterministically and include every
runtime choice that changes the required validation.

Keep the job name stable across these contexts. A later failure of that job
conservatively revokes older proof, including a failure with a different context
or head. This prevents a broader failed suite from being hidden by an older
narrower pass, and the reverse. Missing context defaults to the existing receipt
behavior for jobs whose complete work is fixed by their declared Git inputs.

The optional `input-paths` array binds exact repository-relative files or directories instead of the entire tree. Include source, tests, workflows, setup scripts, lockfiles, configuration, generated-input sources, and pinned tools that can affect the verdict. Globs, absolute paths and ambiguous path segments are rejected.

CI-esta cannot infer external dependencies, changed services, floating container tags, changed secrets or an incomplete input declaration. Use whole-tree identity unless you can audit the narrower set. Pin external inputs and keep scheduled full runs for state outside Git. An identical Git identity is evidence of identical declared inputs, not proof that the universe is unchanged.

## Reuse policy

| Condition | Result |
| --- | --- |
| Same-repository automatic PR, matching receipt, passing first-attempt lane, evidence younger than 24 hours | Eligible for reuse |
| Another lane failed or the overall workflow was cancelled | This lane can still prove its own completed work |
| Missing receipt, failed/cancelled lane, stale or unrelated PR evidence | Execute the lane |
| Newer contradictory failure | Older evidence is revoked according to receipt/head ownership |
| Explicit rerun, manual dispatch, schedule, fork PR | Execute the lane |
| API unavailable | Conservative fallback |

`resolve-incremental-pr-base` is a separate lower-level action for scanners that accept a comparison base. It finds a proven successful ancestor of this PR, defaults to a 168-hour freshness window, and returns the supplied PR base when uncertain. It narrows a scan range; it does not justify skipping an entire test suite.

## Strict required checks

Use `validation-gate` with the aggregate job's direct `needs` and a boolean `required` map containing exactly those job keys. A job must succeed, or be explicitly unneeded and skipped. Failed, cancelled, missing and unexpectedly skipped jobs fail the gate. Keep the planner itself required so a broken admission decision cannot turn the aggregate green.

A gate in selected-lane mode (`lanes` plus `lane-jobs`) is what `ci-esta check-workflow`
verifies, and the check refuses a `required` map. To reuse there, fold the proof into
the planner's lane output instead: after `resolve-lane-evidence`, set a lane to `false`
only when every job it covers is in `reused`, and publish that as the planner's
`lanes` output. Job conditions, `lane-jobs` and the check stay unchanged, and a
partly proven lane runs in full:

```yaml
- id: admit
  env:
    LANES: ${{ steps.plan.outputs.lanes }}
    REUSED: ${{ steps.evidence.outputs.reused || '{}' }}
    LANE_JOBS: '{"py311":"Tests (3.11)","py314":"Tests (3.14)"}'  # the evidence step's lanes input
  run: |
    lanes=$(jq -c --argjson jobs "$LANE_JOBS" --argjson reused "$REUSED" 'if [$jobs | keys[] | $reused[.] == true] | all then .tests = false else . end' <<<"$LANES")
    echo "lanes=$lanes" >> "$GITHUB_OUTPUT"
```

[pytest-quint-connect](https://github.com/gigaverse-app/pytest-quint-connect/blob/main/.github/workflows/ci.yml) uses this for its seven test jobs.

## Permissions

Evidence discovery uses `contents: read`, `actions: read`, and `checks: read`. Complete PR file collection also needs `pull-requests: read`. Do not run untrusted PR code with elevated credentials. These examples use the ordinary `pull_request` event, not `pull_request_target`.

If another workflow calls this one with `workflow_call` (a release workflow that reruns CI on the tag, for
example), the calling job must grant the same permissions. GitHub refuses to start a called workflow whose jobs
request more than the caller grants, so the release fails at startup, with no job logs, the first time it runs
after evidence reuse is adopted. pytest-quint-connect's v1.2.0 Publish failed this way.

## Reuse after a merge

Set `reuse-after-merge: 'true'` and declare complete `input-paths` for jobs whose
execution contract is the same on PRs and branch pushes. A first-attempt push
resolves exactly one merged, same-repository PR whose merge commit matches the
push and whose base branch matches the destination. It then uses the existing
workflow/job/receipt resolver; the merge event itself is never proof. Changed
inputs, stale or missing completion receipts, newer contradictory runs, API
uncertainty and explicit reruns execute fresh validation. No extra permissions
beyond the existing read-only evidence permissions are needed.

**Add the ownership marker; reuse after a merge depends on it.** GitHub often
leaves a run's `pull_requests` empty, even for an ordinary same-repository PR.
The push after the merge then rejects every PR run as "not associated with PR #N"
and executes every lane, with no other symptom. Add this top-level step to the
planning job; nested composite steps are not exposed by the jobs API:

```yaml
- name: "PR evidence #${{ github.event.pull_request.number }} head ${{ github.event.pull_request.head.sha }}"
  if: github.event_name == 'pull_request'
  run: 'true'
```

This marker proves association only; the executed lane still needs its own
successful completion receipt. `ci-esta adoption` reports `reuse-ownership-marker`
when reuse after a merge is enabled without it, and `reuse-receipt` when no step
records the receipt.

The receipt binds the tested merge's inputs. A PR that was behind its base when
it merged, because another PR changed a declared input in between, correctly
executes fresh on the push.

## Root Python release versions

`reuse-version-only-release: 'true'` additionally recognizes a strict Release
Please transition in a root Python project. It requires Python 3.11+, full Git
history, a clean tracked checkout and complete `input-paths`. The only permitted
changes are an increasing stable project version in `pyproject.toml`, the matching
editable root package in `uv.lock`, the matching `.` release manifest entry, and
`CHANGELOG.md`. Every other byte of the Python manifests, including dependency
versions and comments, remains significant. Unknown or inconsistent edits retain
full validation.

This mode binds runtime proof to the validated base's exact inputs and, for a
local first-party action, its old project-version manifests. It still requires
a fresh matching completion receipt from the PR merged at that base; merely
recognizing a version bump cannot skip anything. A previous unsuccessful run of
the release head prevents reaching back to that base proof.

The `release-only` output describes the recognized release transition, not a
successful reuse decision. Consumers must gate skips on the individual `reused`
booleans and keep package build, version metadata, wheel and source-distribution
installation checks mandatory. CI-esta's publishing workflow retains full
exact-tag validation. Publishing, schedules and manual full checkpoints do not
consume this evidence.

**Refresh the release PR after main's CI, not on push.** The proof is the merged
base's completion receipt, which exists only once `main`'s CI has finished on that
commit. If Release Please runs on `push`, the release PR's CI starts while `main`'s
CI on the same code is still running, finds no receipt, and executes every lane.
Trigger Release Please with `workflow_run` after a successful push CI on `main`.
`ci-esta adoption` reports `release-refresh-timing` when version-only reuse is
enabled and Release Please runs on push.
