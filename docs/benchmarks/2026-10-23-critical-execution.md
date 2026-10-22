# Actual execution bottlenecks, 23 October 2026

These measurements target test execution after workflow routing. They are one
hosted before/after pair, not a universal guarantee or a billing estimate.

## Due: parallel, isolated Django conformance

| Metric | Serial, run 39867723644 | Four workers, run 39868243678 | Reduction |
| --- | ---: | ---: | ---: |
| Validation gate elapsed | 538 s | 282 s | 47.6% |
| Execution critical path | 529 s | 273 s | 48.4% |
| Total job execution | 992 runner-s | 569 runner-s | 42.6% |

The observed dependency path is `select-tests → Execute tests (locked) →
tests (locked/minimum) → Validation gate`. Each required test gate depends on
both Django variants. Scheduling/admission delay along the path was 9 seconds
in both runs. The separate Widget Store workflow is excluded from these CI
metrics and passed in both revisions.

The before head is `d88a7e546449cc9853f76e53ec5fa55e1ecc93ee`; after is its
single-child commit `e57f2eda31ceee449e2fe31bcf3c76b04715e846`. The only change
adds four xdist workers with work stealing to the package-export, library and
integration sessions, and retains library JUnit. Dependency locks, application
code, integration tests and every conformance validator are unchanged.

Both Django variants have exactly the same 982 integration test identities and
pass/skip outcomes before and after. All required profile, effect, observation,
replay and crash-history validators passed. pytest-django isolates databases;
live workers use unique queues and their actual worker database name. Worker
reports merge in the controller before validators run. Serial testcase-duration
sums can increase under contention even while concurrent wall time decreases.

Raw [before](2026-10-23-critical-execution/due-39867723644.json),
[after](2026-10-23-critical-execution/due-39868243678.json), and
[matched test inventories](2026-10-23-critical-execution/due-test-inventory.json)
retain provenance and the complete DAG calculation. Source runs:
[before](https://github.com/gigaverse-app/due/actions/runs/39867723644),
[after](https://github.com/gigaverse-app/due/actions/runs/39868243678).

See [the adoption tutorial](../critical-path-optimizations.md) for isolation and
measurement requirements. Keep full checkpoints and validate the complete
evidence after introducing parallel execution.
