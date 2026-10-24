# Reporting runtime and artifact collection

Reporting must remain advisory and preserve source run, attempt, head, missing
evidence and stale-observation handling. Consumers retain their validation gates.

- [x] Run enrichment from an invalid consumer project without touching its environment.
- [x] Reuse one locked environment across timing, enrichment and report calls.
- [x] Overlap independent artifact downloads with at most four workers; preserve order and individual failures.
- [x] Retain reference fallback and stale/foreign/partial measurement controls.
- [x] Exercise public composite actions on a fresh hosted runner (Public action smoke 40109739250).
- [x] Benchmark cold and warm runtime setup plus read-only AI/backend report collection (three alternating samples; payloads identical except observation time).
- [x] Verify both consumer workflows keep reporting outside gate dependencies (AI #3149 and backend #5539 policy tests).
