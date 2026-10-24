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
