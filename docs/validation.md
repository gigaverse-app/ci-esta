# Extraction validation

## Invariants and test plan

- [x] The aggregate gate accepts success or an explicitly unneeded skip, and rejects missing/failed/cancelled prerequisites. `tests/ci/test_validation_gate.py` exercises `validateGate`.
- [x] Reuse requires owned, fresh success, survives unrelated lane failures and rejects contradictory proof. `tests/ci/test_incremental_evidence.py` executes the real resolver against a strict external API fake.
- [x] Incomplete or racing PR file lists cannot become complete evidence. `tests/ci/test_pr_change_evidence.py` executes the collector.
- [x] Receipt identity follows source/tool changes, ignores generated caches, and rejects ambiguous declared paths. `tests/ci/test_portable_receipts.py` exercises actual JavaScript with filesystem/API boundaries.
- [x] The reporter uses pytest-selective's shared explanation contract and accepts repository-neutral timing data. `tests/ci_observability/` covers renderers, collection, artifacts and profiles.
- [x] The installed CLI can render an unavailable report offline without credentials. `tests/test_cli.py` invokes a separate Python process.
- [x] Locked tests on Python 3.11 and 3.14, plus installed-wheel smoke on Python 3.11.
- [x] Hosted CI validates the report action against GitHub's actual run/job APIs.
- [ ] A disposable PR proves successful execution, reuse after an unrelated change, and forced execution on manual rerun.

## Red-team findings

1. The source receipt scanner assumed backend-common directories existed. The portable regression failed; the scanner now hashes CI-esta's sources and manifests, handles absent optional directories, normalizes path separators and excludes bytecode caches.
2. Ambiguous declared paths such as `a/./b` or backslash-separated paths could be interpreted as missing inputs. The regression failed before stricter validation; invalid declarations now fall back conservatively.
3. Timings were readable only through named source-consumer profiles. The generic-profile regression failed; the same authoritative timing model now accepts the neutral `pytest` extension, preserving compatibility adapters.
4. The first live run collected every job but could not match the required gate: the inherited selector used a runner machine name, not a job display name. Added explicit `job_name` selection with exactly-one-identity validation and rejection of ambiguous job matches. The new regression failed before implementation. Original live evidence: [run 39839452342](https://github.com/gigaverse-app/ci-esta/actions/runs/39839452342), revision `36626d1b70dcc77434e866bc23d32c02515aeaf3`.

The initial source test extraction also caught a missing XML runtime dependency; the package declares it. Source-consumer workflow metadata tests remain in backend-common because those workflows are outside the extracted public product. The inherited reporter schema was regenerated against the locked dependencies.

## Live evidence ledger

| Scenario | Revision | Evidence | Result |
| --- | --- | --- | --- |
| First corrected PR validation | `a1cdb72939ad7dab66949ee44c99f81784ae6678` | [run 39840045077](https://github.com/gigaverse-app/ci-esta/actions/runs/39840045077) | Both Python suites executed, gate passed, report collected complete real API evidence |

Local Windows validation on that revision passed 418 tests and Ruff. The actual CLI read the completed first workflow from GitHub and produced a complete report with a 35-second gate elapsed time and 55 observed runner seconds; this is a single workflow observation, not a speedup claim. The publisher sent an actual HTTP PUT to a disposable local HTTP receiver, which returned 202; repository grouping and payload were checked and the receiver shut down. This verifies transport, not a deployed Pushgateway service.

Local API fakes are not counted as live proof. This document records a scoped extraction check, not exhaustive correctness or a benchmark.
