# Runner and cache reporting

- [x] Runner identity survives GitHub collection and appears in the Markdown report.
- [x] Pytest advice appears only when pytest evidence exists.
- [x] Native cache outputs distinguish exact/fallback/miss/skipped/unavailable without granting test reuse.
- [x] Artifact provenance rejects other attempts and repositories; ambiguous/missing step timings remain unknown.
- [x] Real Bun runs locked installation repeatedly and propagates installation failures.
- [x] Public action smoke executes cold, warm and fallback dependency setup and inspects published measurements. Run 40132822596, attempt 1, commit 45927127c6f54175ea61663c9f01e07d561b018f.
- [ ] Web App Checks and Egress Build Check publish dependency/compiler/tool outcomes from real runs.
- [ ] Render the candidate report against those runs and verify runner identity and cache tables.
