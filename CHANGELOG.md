# Changelog

## [1.1.4](https://github.com/gigaverse-app/ci-esta/compare/v1.1.3...v1.1.4) (2026-10-23)


### Bug fixes

* **docs:** refresh cached artwork when branding changes ([49ffd45](https://github.com/gigaverse-app/ci-esta/commit/49ffd45bcea1498f904c5a39d38a088e4bc15d72))
* **report:** unify Python and Bun headlines and publication ([360e170](https://github.com/gigaverse-app/ci-esta/commit/360e17064c777ad75678dbd0d96472d1ce9ae4e1))

## [1.1.3](https://github.com/gigaverse-app/ci-esta/compare/v1.1.2...v1.1.3) (2026-10-23)


### Bug fixes

* **report:** restore the approved sticky layout ([#67](https://github.com/gigaverse-app/ci-esta/issues/67)) ([5e196ba](https://github.com/gigaverse-app/ci-esta/commit/5e196ba7fe2acebc515a47288a19587ba7d67688))

## [1.1.2](https://github.com/gigaverse-app/ci-esta/compare/v1.1.1...v1.1.2) (2026-10-23)


### Bug fixes

* **report:** render shared pytest timing totals once ([#65](https://github.com/gigaverse-app/ci-esta/issues/65)) ([ae330a5](https://github.com/gigaverse-app/ci-esta/commit/ae330a539dc048c439a34730bdbe4d6c607a5851))

## [1.1.1](https://github.com/gigaverse-app/ci-esta/compare/v1.1.0...v1.1.1) (2026-10-23)


### Bug fixes

* **actions:** use the stable selector action API ([#62](https://github.com/gigaverse-app/ci-esta/issues/62)) ([a184c33](https://github.com/gigaverse-app/ci-esta/commit/a184c33f639cee2bcd163f7ac4d692659870bcd4))

## [1.1.0](https://github.com/gigaverse-app/ci-esta/compare/v1.0.0...v1.1.0) (2026-10-23)


### ⚠ BREAKING CHANGES

* **actions:** named action callers upgrading from older layouts must replace `.github/actions/NAME` or `NAME` with `actions/NAME` and select a revision containing that path.

### Features

* **actions:** group public entry points under actions directory ([#56](https://github.com/gigaverse-app/ci-esta/issues/56)) ([29c2008](https://github.com/gigaverse-app/ci-esta/commit/29c2008efb36d17bd4ddcc688f86e365f937152d))
* **report:** expose measured reuse, caches and shard efficiency ([#55](https://github.com/gigaverse-app/ci-esta/issues/55)) ([9cbd40e](https://github.com/gigaverse-app/ci-esta/commit/9cbd40ee1eac770348683ee22a4b1dd838f4486d))


### Bug fixes

* **actions:** keep the v1 API independent of package versions ([#61](https://github.com/gigaverse-app/ci-esta/issues/61)) ([698469b](https://github.com/gigaverse-app/ci-esta/commit/698469b4561f639ab2a4f54607028d6d8b991ca8))


### Refactoring

* **actions:** move implementations into the public actions directory ([#59](https://github.com/gigaverse-app/ci-esta/issues/59)) ([df41034](https://github.com/gigaverse-app/ci-esta/commit/df410342aa4bf53fd743b8c5d82e951cffb29492))

## [1.0.0](https://github.com/gigaverse-app/ci-esta/compare/v0.4.0...v1.0.0) (2026-10-23)


### Features

* publish stable major action aliases ([29d10d4](https://github.com/gigaverse-app/ci-esta/commit/29d10d42f1e364ab4cac10441558129b08c87cac))

## [0.4.0](https://github.com/gigaverse-app/ci-esta/compare/v0.3.0...v0.4.0) (2026-10-23)


### Features

* add public action entry points and task-focused onboarding ([#51](https://github.com/gigaverse-app/ci-esta/issues/51)) ([ecfbdca](https://github.com/gigaverse-app/ci-esta/commit/ecfbdca0fd895276e2f7503629d659485bd3b070))

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
