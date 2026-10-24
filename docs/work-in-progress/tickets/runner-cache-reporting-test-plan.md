# Runner and cache reporting

- [x] Runner identity survives GitHub collection and appears in the Markdown report.
- [x] Pytest advice appears only when pytest evidence exists.
- [x] Native cache outputs distinguish exact/fallback/miss/skipped/unavailable without granting test reuse.
- [x] Artifact provenance rejects other attempts and repositories; ambiguous/missing step timings remain unknown.
- [x] Real Bun runs locked installation repeatedly and propagates installation failures.
- [x] Public action smoke executes cold, warm and fallback dependency setup and inspects published measurements. Run 40132822596, attempt 1, commit 45927127c6f54175ea61663c9f01e07d561b018f.
- [x] Web App Checks 40133042583 and Egress Build Check 40133042550 publish dependency/compiler/tool outcomes from real runs, attempt 1, head 5a8d2f2fb592cc24ee169e6e4a1b52f52b04ac42.
- [x] Candidate observers 40133892036 and 40133384036 render runner identity and cache tables; the App Checks sticky is comment 6389687936 on web PR 4267.
- [x] Disabling download caching preserves frozen installation, reports skipped restoration and leaves restore/save durations unknown. Public action smoke 40133884022, attempt 1, head deecb809f3e6e1cd3912fb0a7761184e46fc22d6.
- [x] Compare download, installed-tree, legacy and uncached setup on the same web revision, including key computation, restore, mandatory installation and save. Run 40134362184, attempts 1 and 2; evidence is in docs/benchmarks/2026-10-24-bun-cache.md.
