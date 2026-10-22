# CI-esta migration test plan

The reusable CI implementation moves to CI-esta. backend-common retains its application runtime, release/bump orchestration and compatibility entry points. pytest-selective remains the owner of dependency analysis and shard planning.

## Invariants

- Historical Python imports, module patches, CLI exits, action inputs/outputs and fallback behavior remain usable.
- Retags of byte-identical backend-common dependencies still reuse positive evidence; failures and manual reruns still execute.
- There is one implementation of each migrated algorithm. Compatibility actions delegate to an immutable upstream commit; Python aliases use the locked dependency.
- Shell resources ship in the wheel and work outside both repositories.
- Every extracted source file and test has an explicit disposition; application/Kafka helpers and repository release policy stay here.

## Verification

1. Inventory source revision and upstream baseline; preserve tests before moving ownership.
2. Run migrated behavioral tests upstream, then module identity and action contract checks here.
3. Build/install the wheel in isolation, exercise CLIs and actual Actions API reporting.
4. Run source CI and generated consumer bump CI; inspect individual job results and artifacts.
5. Record revision-bound results and remaining gates before merging.

## Evidence ledger

- `c990c5426301284edf3a99ae34593080afc8580c`: [hosted run 39845148497](https://github.com/gigaverse-app/ci-esta/actions/runs/39845148497) passed both Python versions, wheel build/install and real Actions API reporting. The extracted suite contains 979 tests.
- The loop caught and repaired lost shell executable modes, the Python 3.14 parser runtime requirement, unsafe test-generated files entering the sdist, historical image-observer import compatibility, and dependency retag normalization.
- backend-common's migration remains under verification in PR269. Its local migration-domain run passed 1,211 tests (56 skips); 74 compatibility contracts passed, and targeted alias type checking reports zero errors. These are development-tree results, not evidence of a merged consumer deployment.
- Workflow change classification and current-head admission are a subsequent extraction batch. Their local public-boundary tests pass; hosted verification and downstream adoption remain pending.

Completion requires the final source revision and generated consumer checks. Earlier green runs do not substitute for those gates.

## Canonical pytest guard ownership

The global pytest expansion and file-isolation implementations and their 70 preservation tests move to pytest-selective PR11. CI-esta retains module-identity aliases and an immutable action delegate. Its remaining suite passes 915 tests locally on Python 3.11; the selector preservation suite passed 68 tests on Windows (two POSIX action cases skipped), and its initial hosted matrix passed every platform. New lock metadata restores the compiled coverage tracer for Python 3.11 without changing the coverage version. The final selector and CI-esta revisions still require their own hosted checks.

backend-common source revision5018aae passed its hosted tests, types, CI-code and canary checks. Generated consumer PRs gigaverse-backend5495 and gigaverse-ai3109 both reported passing required gates. Running the installed migrated CLI against source test run39847640693 produced a complete report: 110 runner-seconds and 113 seconds to its explicit Run pytest gate. Later pin/schema changes must be checked again before source merge.
