# CI-esta for non-Python repositories

This optional-provider boundary is available from the current Git revision;
published 0.1.0 predates it. Install from the checkout (`pip install .`) or use
the reviewed immutable Actions revision.

CI-esta measures GitHub Actions jobs regardless of application language. Its base
Python package installs neither pytest nor pytest-selective. The hosted reporter
provides its own Python runtime; your application does not need Python dependencies.

Timing, critical-path analysis, runner estimates, completion receipts and required
validation gates work with Bun, TypeScript, browser tests, builds and other tools.
[Evidence reuse](evidence-reuse.md) requires matching declared inputs and completed
validation, including execution scope and external identities where relevant.

## One sticky, optional providers

CI-esta owns the sticky, accounting and admission evidence. pytest-selective owns
Python dependency analysis, collection semantics and selection explanations.
Existing Python artifacts remain supported through `ci-esta[selection]`; pytest
execution tools use `ci-esta[pytest]`. The Actions reporter automatically installs
the selection extra when either legacy selection artifact input is nonempty.
For a base-only observer, set both `lane-selection-artifact` and
`test-selection-artifact` to empty strings. Existing Python callers keep their
rich sections without changing their artifact format.

A non-Python selector or admission planner can upload one JSON file as an artifact
and pass its name as `work-selection-artifact` to the reusable reporting workflow:

```json
{
  "schema_version": "ci-esta/work-selection/v1",
  "provider": "bun-checks",
  "run_id": 123,
  "run_attempt": 1,
  "head_sha": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "input_identity": "tested merge tree identity",
  "fallback": false,
  "decisions": [
    {
      "name": "Bun unit/integration tests",
      "decision": "reused",
      "reason": "Matching completed validation for the same declared work",
      "receipt": "the completion receipt returned by resolve-lane-evidence"
    }
  ]
}
```

Use the observed source run's identity, including attempt and PR head SHA.
`run` requests execution, `unaffected` records a selector's decision, and `reused`
records prior successful validation with a matched receipt. They are distinct
from execution results. The report's actual jobs and gates determine success;
this artifact is explanatory data and never authorizes skipping work.

The schema is bounded, rejects duplicate work names and rejects skipping during
fallback. Missing, malformed, foreign-repository or mismatched-identity artifacts
cannot replace run facts; the reporter keeps timing and gates available. The
sticky explains each decision without presenting requested work as tests passed
or inventing savings without a measured comparison.

Existing saved Python reports can still be read without the optional dependency:
their original selection payloads survive JSON round trips and the sticky explains
which extra renders those details. Installing the extra restores the full view.

## Validate an adoption

Compare a successful full execution and eligible repeat on the same tested
revision and contract. Keep explicit reruns and manual/full checkpoints executing,
and verify changed inputs and missing proof execute too. Report elapsed time and
summed runner-seconds separately, including observer overhead separately. A single
pair is an observation, not a universal speedup or a billing claim.
