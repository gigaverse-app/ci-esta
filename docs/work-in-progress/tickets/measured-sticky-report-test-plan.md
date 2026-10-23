# Measured sticky report

## Invariants and verification

- [x] Baseline on `91d2975`: 247 report, timing-action and local-shard tests pass.
- [x] Preserve banner, selection explanations, startup floor, Gantt, gates, costs,
  slow steps, overlap, benchmark and Bun details behind their owning sections.
- [x] A selection plan never claims execution or receipt reuse. Unknown savings
  remain unknown; historical comparisons remain estimates with their sources.
- [x] Successful cache records follow locked validation; cache hits do not imply
  a measured time saving. Failed validation cannot publish a successful record.
- [x] Reuse telemetry describes the resolver's admitted source jobs and current
  run/attempt/head. Reporting failure cannot change validation admission.
- [x] Local shards record observed process intervals, including failed children.
  Occupancy uses allocated slots and observed intervals, never summed JUnit time.
  Incomplete pools, duplicates and stale identities cannot inflate totals.
- [x] Existing action harnesses exercise the real resolver with API-boundary fakes;
  local process tests exercise the actual shard runner. Missing telemetry preserves
  the rest of the report.
- [ ] Full local checks and hosted CI pass on the published revision.
- [x] Real GitHub report includes measured cache/reuse and shard artifacts; inspect
  the actual sticky and JSON. Exercise positive execution and reuse controls.
- [ ] Release through Release Please, verify exact PyPI installation, update all
  consumers, and inspect their resulting reports and validation gates.

## Evidence ledger

Baseline: `91d2975`, 247 passed. Implementation, CI, live report, release and
consumer adoption evidence will be recorded here as each gate is completed.

First implementation pass: 529 targeted tests passed (reporting, real shard
processes, real JavaScript resolver/action code, environment validation), plus
Ruff and both import contracts. Fail-first controls reproduced missing process
records and missing proof callbacks. Report regressions exposed a pre-existing
zero-offset Gantt omission; jobs beginning at the workflow timestamp now retain
their bars. Telemetry tests also bind PR head separately from the tested merge.

Frozen `83c1744`: full Linux suite **1,174 passed**, wheel and sdist built.
Hosted run `39939766004` exercised the real actions and revealed two integration
issues: main had gained generated public action wrappers (the new shard publisher
needed one), and the jobs API hides inner composite steps. Cache/image recording
therefore uses small source-bound artifacts instead of unobservable step names.
Main through `bea0fd0` was merged without conflicts; wrappers were regenerated.
The new stdlib producer is exercised through its actual CLI and fed through the
collector/renderer. Real locked-sync controls cover success, lock drift and an
unwritable telemetry output, preserving validation in every case.

Frozen `4e36a83`: full Linux suite **1,214 passed**, wheel and sdist built.
Live artifact collection on run `39940622998` recorded three real cache misses
and their locked-sync durations, with zero claimed reuse and the failed gate
correctly shown as blocked. The hosted merge included another new public namespace
from main; adding its generated wrapper fixed the only test failure.
Hosted run `39941029166` on `9f6261a` is green, including both Python versions,
quality, packaging and the validation gate. This documentation-only ledger update
is the positive same-input receipt-reuse control for that successful execution.

Hosted unchanged-input control `39941332933` skipped both Python lanes using
successful source run `39941029166`; the report resolved both source jobs through
GitHub and displayed 44s + 49s = approximately 1m33s runner time avoided. The gate
passed; no new test execution or wall-time savings were claimed.

Main's action implementation move (`df41034`) was merged into `fdd4267`; all
measurement additions moved to the canonical `actions/` owners. Full frozen Linux
suite: **1,236 passed**, wheel and sdist built. Hosted public action smoke
`39942526740` executed actual pytest files with `run-local`, uploaded intervals
through `actions/publish-shard-measurements`, and produced a complete live report:
2 shards, 4 visible CPUs, 72% observed slot occupancy, 1.10s / 2.50s child
intervals. This small smoke proves measurement plumbing, not production savings.
The source API cache outcome was one validated miss. Banner, Gantt and per-shard
raw details survived rendering. A fail-first partial-proof regression now keeps
valid reused lanes when another source job is unreadable.
