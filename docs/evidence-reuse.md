# Reuse successful GitHub Actions jobs safely

A skipped job is not proof that its work passed. CI-esta reuses a lane only when a prior successful job carries a matching completion receipt. The receipt binds the tested inputs and the downloaded CI-esta implementation. An unavailable API or uncertain proof runs more work.

## Start with the whole tree

Use `gigaverse-app/ci-esta/actions/resolve-lane-evidence@v1` with a `lanes` JSON map of output keys to exact job names. Pin a reviewed commit SHA for production. Omitting `input-paths` binds the merged tree, base commit, and head tree. Recreated merge commits can match; changed inputs cannot.

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

## Permissions

Evidence discovery uses `contents: read`, `actions: read`, and `checks: read`. Complete PR file collection also needs `pull-requests: read`. Do not run untrusted PR code with elevated credentials. These examples use the ordinary `pull_request` event, not `pull_request_target`.
