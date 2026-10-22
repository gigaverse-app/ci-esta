# Diagnostics and runner reuse preservation plan

The second extraction brings Linux resource diagnostics and opt-in pytest hang diagnostics from gigaverse-backend into CI-esta. Runner labels, service setup and architecture policy remain consumer configuration. CI-esta owns bounded execution ranges; pytest-selective owns file selection and duration balancing.

| Invariant | Enforcement and verification |
| --- | --- |
| Diagnostics preserve command output and exit status | Run real successful/failing commands through the installed resource CLI, enabled and disabled; ensure monitor cleanup does not hold output pipes open |
| A hung test is diagnosed without becoming a passing test | Real pytest subprocess exceeds the watchdog deadline, then fails; require stack diagnostics and failure status |
| Post-session thread leaks preserve the determined exit status | Real passing/failing pytest subprocesses leak a non-daemon thread; require bounded termination with the original status |
| Shards cover the global plan exactly once | Exercise public pool CLI with uneven ranges, invalid requests and consumer matrix wiring; global shard IDs must remain unchanged |
| Standard architecture contracts use import-linter | Exercise real lint-imports pass/fail contracts; retain recursive path/test pairing checks until the violation corpus establishes equivalence |
| Removing duplicate tests loses no distinct behavior | AST inventory plus review of every differing case; canonical selector tests run upstream, installed-package compatibility checks stay in backend-common |

Verification uses frozen local batches, distributions installed outside the checkout, hosted upstream CI, generated backend-common consumer PRs and actual CI diagnostics. Runtime and cost claims require revision-bound measured runs. This plan records intended checks, not completed evidence.
