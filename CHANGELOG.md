# Changelog

## 0.1.2 (2026-10-23)

- Adopt pytest-selective 0.1.1 and preserve prior-failure canary plans when native local selection is enabled. Canary collection and execution explicitly disable re-selection, including when pytest plugin autoload is disabled.
- Keep pytest selection optional for core CI reporting; install the `selection` or `pytest` extra for Python test tooling.
- Measure rerun critical paths from the current attempt rather than counting the wait since the original run.

## 0.1.1 (2026-10-23)

- Match PostgreSQL client tools to the service image so cached test databases restore across runner image updates.

## 0.1.0 (2026-10-23)

First PyPI and GitHub release.

- GitHub Actions timing reports, dependency critical paths, and execution evidence.
- Conservative lane reuse, completion receipts, and strict aggregate gates.
- Test-pool execution, learned timings, resource diagnostics, and isolated Postgres helpers.
- Packaged action support resources and public command-line tools.
- Compatible pytest-selective dependency and versioned Actions references.
