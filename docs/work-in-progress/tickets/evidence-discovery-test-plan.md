# Evidence discovery refactor validation

Exercise the real action/resolver and reporter entry points, replacing only the GitHub API boundary. Positive controls must retain useful proof; negative controls must retain validation.

- [x] Proof beyond ten candidates and on a second metadata page remains usable.
- [x] A newer failure on another page revokes an older success.
- [x] An incomplete service index never exposes old success through fallback.
- [x] Named unrelated checks cause no run-detail reads; relevant checks recover listing lag.
- [x] A comparison 403 stops candidates and other lanes.
- [x] PR refusal cannot disappear when switching to default-branch proof.
- [x] A newer trusted pass can supersede an older known PR failure.
- [x] Failed reruns, including old creation dates, revoke default-branch proof.
- [x] Unknown newer job evidence and an attempt race retain execution.
- [x] Full-suite reporting skips reference search; narrowed reporting retains it.
- [x] Reference throttling stops subsequent batches without losing the report.
- [x] First-attempt billing reuses latest jobs; reruns still fetch history.
- [x] Complete integration tests, lint, build and documentation checks.
- [ ] Verify the changed public action on hosted CI and inspect discovery logs.

The real-system audit uses captured live GitHub responses from CI-esta #209 and its planner logs, plus workflow/run inventories from gigaverse-ai #3430. Execution snapshots stay outside the repository; the PR records the method and concise results. This proves request selection on those cases, not an installation-wide historical quota ledger.
