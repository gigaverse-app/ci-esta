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
- [x] Full local checks and hosted CI pass on the published revision.
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

The feature shipped in Python 1.1.0, followed by 1.1.1's canonical selector
delegation. Publish runs `39945266185` and `39946769471` passed, and exact PyPI
installs were checked outside the source checkout. Actions remain on `v1`,
independently of Python versions. Canonical-only public smoke `39948203418`
passed on `4438f46` after the last legacy action alias was removed.

Due#95, pytest-obligation#118 and pytest-selective#48 merged their adoption.
Web#4259 and mobile#3733 passed CI and await required independent reviews.
Common#280's own checks passed; generated backend#5517 and AI#3127 are testing
their adaptations before the common merge and automatic final pin updates.
Real consumer reports `39947935251` (backend) and `39947524670` (AI) contain
12/16 shards on 16 visible logical CPUs at 92%/94% slot occupancy respectively.
They retain failed child exits and show blocked validation correctly. Backend
also recorded five validated environment misses and one verified image reuse;
AI explicitly recorded disabled environment caching. These are observed runs,
not claims about incremental savings or CPU utilization.

Live AI inspection found duplicate JUnit totals from its structured extension
and legacy repository signal. The production AI enrichment producer reproduces
the duplicate in a fail-first regression; rendering now uses the structured
timing once and preserves legacy-only fallback plus both raw JSON fields.
Consumer failures were stale assertions of the pre-v1 action namespace/version,
corrected without changing validation gates or test coverage.
