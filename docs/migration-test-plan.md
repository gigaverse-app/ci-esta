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

Status: inventory in progress; no migration validation claimed yet.
