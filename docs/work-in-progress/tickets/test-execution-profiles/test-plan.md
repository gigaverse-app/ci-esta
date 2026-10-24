# Execution policy test plan

See [the design](../../../test-execution-policy.md) for source provenance and invariants.

- Exercise affected, empty, unknown, all and explicit scopes through the public CLI.
- Reject disallowed occasions/effects, invalid scope, mismatched environment and deployed revision.
- Preserve AI provider order and exact pins; require capabilities, fail conflicts without leaking values.
- Test elapsed-budget exhaustion and cleanup reserve.
- Verify generated schemas match runtime models.
- Run public action smoke and installed-wheel checks on Linux in Python 3.11 and 3.14 CI.
- Consumer fixtures install the same immutable revision as their planners; AI also exercises actual selector requests.
- Preserve native selection and required-gate tests. Never claim a skipped/live probe passed.


## Opinionated defaults consolidation

- [x] Public API/CLI admission across ci, thorough, full/deep, weekly, smoke, performance and explicit probes.
- [x] Partial overrides, inheritance, empty permission replacement, unknown fields/parents, cycles and defaults:none.
- [x] Selector-owned inventories, unknown metadata rejection and missing-inventory failure.
- [x] Existing consumer parity fixtures and actual workflow-input contracts, with no planner mocks.
- [x] Installed-wheel and real public-action smoke at implementation revision `f529ac3a0621870d836ec0c7ec7f3b13d46f4df4`.

Validation: 1,436 tests passed on Python 3.11; Python 3.14 and public-action smoke also passed at `f529ac3`. Consumer routing contracts passed at their corresponding pinned adoption heads.
