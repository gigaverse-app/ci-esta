# Keep required checks meaningful when test lanes are skipped

Give branch protection and the observer one stable `Validation gate`. It must
depend on every validation job, directly or through another complete gate.
The gate succeeds only when required work succeeded or a successful selector
explicitly declared a conditional lane unnecessary. A missing lane, string
`"false"`, failed planner or unexpectedly skipped metadata job is not permission
to skip work.

```yaml
validation-gate:
  name: Validation gate
  needs: [select-tests, tests, metadata]
  if: ${{ !cancelled() }}
  runs-on: ubuntu-latest
  steps:
    - uses: gigaverse-app/ci-esta/actions/validation-gate@v1
      with:
        needs: ${{ toJSON(needs) }}
        lanes: ${{ needs.select-tests.outputs.lanes || '{}' }}
        lane-jobs: '{"tests":["unit"]}'
```

Here `tests` must execute the complete unit lane when selected. `metadata` and
`select-tests` remain mandatory because they are not optional entries in
`lane-jobs`. A job requiring several lanes can list them all; it is optional
only when every corresponding value is the boolean `false`. The existing
`required` boolean-map input remains available for receipt-based admission.
Do not combine receipt reuse with the lane example by silently omitting jobs.

Keep the aggregate contract synchronized with actual job routing:

```bash
ci-esta check-workflow --workflow .github/workflows/ci.yml --lanes .github/test-lanes.json
```

Run this in the always-running quality job with real Git routing regressions.
It checks that the gate covers all workflow jobs and that its lane mapping
matches the execution conditions and configured lane names. This validator
supports the documented `fromJSON(needs.<planner>.outputs.lanes).<lane>` consumer
pattern; different admission policies need their own tests. It does not infer
conformance guarantees from a green status.

Point the completed-run observer at `Validation gate`, rather than at optional
matrix cells. Set `analyze-critical-path: true` to report the dependency path to
that stable gate. Intentional skips then remain truthful and the observer has
a well-defined completion target for both full and docs-only runs.
