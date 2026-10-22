# Extraction validation

## Invariants and test plan

- [x] The aggregate gate accepts success or an explicitly unneeded skip, and rejects missing/failed/cancelled prerequisites. `tests/ci/test_validation_gate.py` exercises `validateGate`.
- [x] Reuse requires owned, fresh success, survives unrelated lane failures and rejects contradictory proof. `tests/ci/test_incremental_evidence.py` executes the real resolver against a strict external API fake.
- [x] Incomplete or racing PR file lists cannot become complete evidence. `tests/ci/test_pr_change_evidence.py` executes the collector.
- [x] Receipt identity follows source/tool changes, ignores generated caches, and rejects ambiguous declared paths. `tests/ci/test_portable_receipts.py` exercises actual JavaScript with filesystem/API boundaries.
- [x] The reporter uses pytest-selective's shared explanation contract and accepts repository-neutral timing data. `tests/ci_observability/` covers renderers, collection, artifacts and profiles.
- [x] The installed CLI can render an unavailable report offline without credentials. `tests/test_cli.py` invokes a separate Python process.
- [ ] Locked tests and wheel smoke on Python 3.11 and 3.14.
- [ ] Hosted CI validates the report action against GitHub's actual run/job APIs.
- [ ] A disposable PR proves successful execution, reuse after an unrelated change, and forced execution on manual rerun.

## Red-team findings

1. The source receipt scanner assumed backend-common directories existed. The portable regression failed; the scanner now hashes CI-esta's sources and manifests, handles absent optional directories, normalizes path separators and excludes bytecode caches.
2. Ambiguous declared paths such as `a/./b` or backslash-separated paths could be interpreted as missing inputs. The regression failed before stricter validation; invalid declarations now fall back conservatively.
3. Timings were readable only through named source-consumer profiles. The generic-profile regression failed; the same authoritative timing model now accepts the neutral `pytest` extension, preserving compatibility adapters.

The initial source test extraction also caught a missing XML runtime dependency; the package declares it. Source-consumer workflow metadata tests remain in backend-common because those workflows are outside the extracted public product. The inherited reporter schema was regenerated against the locked dependencies.

Live evidence links and immutable revisions are added after hosted verification. Local API fakes are not counted as live proof. This document records a scoped extraction check, not exhaustive correctness or a benchmark.
