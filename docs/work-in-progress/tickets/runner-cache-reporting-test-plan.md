# Runner and cache reporting

- [x] Runner identity survives GitHub collection and appears in the Markdown report.
- [x] Pytest advice appears only when pytest evidence exists.
- [x] Native cache outputs distinguish exact/fallback/miss/skipped/unavailable without granting test reuse.
- [x] Artifact provenance rejects other attempts and repositories; ambiguous/missing step timings remain unknown.
- [x] Real Bun runs locked installation repeatedly and propagates installation failures.
- [ ] Public action smoke executes cold then warm dependency setup and inspects published measurements.
- [ ] Web App Checks and Egress Build Check publish dependency/compiler/tool outcomes from real runs.
- [ ] Render the candidate report against those runs and verify runner identity and cache tables.
