# Changelog

## [0.3.0](https://github.com/gigaverse-app/ci-esta/compare/v0.2.2...v0.3.0) (2026-10-23)


### Features

* **report:** lead with verified impact and Bun execution evidence ([#49](https://github.com/gigaverse-app/ci-esta/issues/49)) ([91d2975](https://github.com/gigaverse-app/ci-esta/commit/91d2975f8580811550fa757cf5ba3fe118a381b4))

## [0.2.2](https://github.com/gigaverse-app/ci-esta/compare/v0.2.1...v0.2.2) (2026-10-23)


### Bug fixes

* **report:** measure completed gates before downstream publication ([#47](https://github.com/gigaverse-app/ci-esta/issues/47)) ([7fd7f61](https://github.com/gigaverse-app/ci-esta/commit/7fd7f61aacaf0b14a446001f06f8a7f2c63d6a20))

## [0.2.1](https://github.com/gigaverse-app/ci-esta/compare/v0.2.0...v0.2.1) (2026-10-23)


### Bug fixes

* **setup:** preserve caller uv conformance versions ([#44](https://github.com/gigaverse-app/ci-esta/issues/44)) ([7e522bf](https://github.com/gigaverse-app/ci-esta/commit/7e522bfebcdba1dcb3c82857b7a3463b8c46136b))

## [0.2.0](https://github.com/gigaverse-app/ci-esta/compare/v0.1.2...v0.2.0) (2026-10-23)


### Features

* **ci:** expand reusable workflow critical paths ([#39](https://github.com/gigaverse-app/ci-esta/issues/39)) ([7c87180](https://github.com/gigaverse-app/ci-esta/commit/7c87180aae89ae351e825ed99ae42eb5217d79e3))


### Bug fixes

* **report:** preserve source identity and show unavailable usage honestly ([#40](https://github.com/gigaverse-app/ci-esta/issues/40)) ([d880533](https://github.com/gigaverse-app/ci-esta/commit/d8805330dd08f8dfe517503902bcfe752685ce2e))

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
