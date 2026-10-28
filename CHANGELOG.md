# Changelog

## [1.6.3](https://github.com/gigaverse-app/ci-esta/compare/v1.6.2...v1.6.3) (2026-10-28)


### Bug fixes

* **report:** count reused contracts behind aggregate gates ([#121](https://github.com/gigaverse-app/ci-esta/issues/121)) ([9ca9f70](https://github.com/gigaverse-app/ci-esta/commit/9ca9f70935b57aa50cfac677a5b1bb5f4dbe4822))
* **report:** refresh stale jobs after workflow completion ([#119](https://github.com/gigaverse-app/ci-esta/issues/119)) ([4dd8e64](https://github.com/gigaverse-app/ci-esta/commit/4dd8e64324d06e55292c91509aa5152703932058))

## [1.6.2](https://github.com/gigaverse-app/ci-esta/compare/v1.6.1...v1.6.2) (2026-10-26)


### Bug fixes

* **ci:** unify Python selection policy and validation evidence ([#117](https://github.com/gigaverse-app/ci-esta/issues/117)) ([d4347d5](https://github.com/gigaverse-app/ci-esta/commit/d4347d515da456263bfb7ebbdc21a9a486e9e836))
* **report:** distinguish CI gate completion from merge readiness ([#114](https://github.com/gigaverse-app/ci-esta/issues/114)) ([c101f10](https://github.com/gigaverse-app/ci-esta/commit/c101f1085b66ba2904b2e0605fc933d88add62f3))
* **report:** retain reports when test summaries exceed the display limit ([#115](https://github.com/gigaverse-app/ci-esta/issues/115)) ([e14c416](https://github.com/gigaverse-app/ci-esta/commit/e14c416310bb5e781d162a7359e4e9e71b927534))

## [1.6.1](https://github.com/gigaverse-app/ci-esta/compare/v1.6.0...v1.6.1) (2026-10-24)


### Bug fixes

* **ci:** align validation inputs and reuse accounting ([5e6059d](https://github.com/gigaverse-app/ci-esta/commit/5e6059d4e6bf9ab415a8d4de6fa2dc85ebefc06d))


### Performance

* **ci:** reuse merged validation for version-only releases ([2f363d0](https://github.com/gigaverse-app/ci-esta/commit/2f363d081b59484c8cc1bf16c6965c28e74cea7c))

## [1.6.0](https://github.com/gigaverse-app/ci-esta/compare/v1.5.1...v1.6.0) (2026-10-24)


### Features

* **cache:** report Bun setup and runner identity ([#108](https://github.com/gigaverse-app/ci-esta/issues/108)) ([29fd9b9](https://github.com/gigaverse-app/ci-esta/commit/29fd9b907a81064b9986cc92a0b59de08857ac91))
* **ci:** report bun capacity and require validated selection bases ([#110](https://github.com/gigaverse-app/ci-esta/issues/110)) ([aa9a171](https://github.com/gigaverse-app/ci-esta/commit/aa9a1711e9a58f49203016b1a05ddc0c8527fd37))

## [1.5.1](https://github.com/gigaverse-app/ci-esta/compare/v1.5.0...v1.5.1) (2026-10-24)


### Bug fixes

* **ci:** unblock secure consumers and deduplicate receipt reads ([#106](https://github.com/gigaverse-app/ci-esta/issues/106)) ([1edd5a9](https://github.com/gigaverse-app/ci-esta/commit/1edd5a96fbb7163e5922249bbd326e67ca2096dd))

## [1.5.0](https://github.com/gigaverse-app/ci-esta/compare/v1.4.2...v1.5.0) (2026-10-24)


### Features

* **ci:** centralize test policy and reusable execution mechanisms ([#98](https://github.com/gigaverse-app/ci-esta/issues/98)) ([3c476cd](https://github.com/gigaverse-app/ci-esta/commit/3c476cda3bc7d70c959ee6f52321b24e3aa942c0))
* **policy:** distinguish affected and affected-deep test profiles ([#104](https://github.com/gigaverse-app/ci-esta/issues/104)) ([7e0d65f](https://github.com/gigaverse-app/ci-esta/commit/7e0d65f81582046cd566f9615db50ddea85cc50e))

## [1.4.2](https://github.com/gigaverse-app/ci-esta/compare/v1.4.1...v1.4.2) (2026-10-24)


### Bug fixes

* **actions:** resolve reporting interpreters across platforms ([8fbbbfa](https://github.com/gigaverse-app/ci-esta/commit/8fbbbfa8c2b75d00c1c4ab7a2094822694ffdeec))
* **report:** align sticky metrics and compact header badges ([#100](https://github.com/gigaverse-app/ci-esta/issues/100)) ([a80ee5d](https://github.com/gigaverse-app/ci-esta/commit/a80ee5d695fe7fd3c3b44bfd47f3ee002f0a4173))
* **report:** centralize GitHub runner SKU prices ([#99](https://github.com/gigaverse-app/ci-esta/issues/99)) ([f53a36e](https://github.com/gigaverse-app/ci-esta/commit/f53a36e0461211d73f273a3913db2dcb182a12cc))
* **report:** recover observed sticky metrics and runner prices ([#96](https://github.com/gigaverse-app/ci-esta/issues/96)) ([5b8fb5a](https://github.com/gigaverse-app/ci-esta/commit/5b8fb5ae20b5bf465eb6b930047efebf2b6db2ee))
* **report:** show the actual test selection reason ([5486501](https://github.com/gigaverse-app/ci-esta/commit/5486501f9961b53d1f6b336f5f90b446c23994f7))

## [1.4.1](https://github.com/gigaverse-app/ci-esta/compare/v1.4.0...v1.4.1) (2026-10-24)


### Bug fixes

* **actions:** install the typecheck scope toolchain ([69e156f](https://github.com/gigaverse-app/ci-esta/commit/69e156fdf400c6d899167d5401d87ce4f46dd55e))


### Performance

* **actions:** overlap service pulls and use locked timing runtimes ([e56e382](https://github.com/gigaverse-app/ci-esta/commit/e56e382c3d4ca625d54e2aaeb9d2f6ef9cbf7dbb))
* **reporting:** reuse locked runtimes and overlap artifact reads ([28a5bd0](https://github.com/gigaverse-app/ci-esta/commit/28a5bd09aa9db2886d112ec1e32f351d73b07888))

## [1.4.0](https://github.com/gigaverse-app/ci-esta/compare/v1.3.1...v1.4.0) (2026-10-24)


### Features

* **adoption:** report integration gaps and share selector defaults ([#90](https://github.com/gigaverse-app/ci-esta/issues/90)) ([070ef1a](https://github.com/gigaverse-app/ci-esta/commit/070ef1a2819f7d86e7ecf67a3a94c61f71a85380))

## [1.3.1](https://github.com/gigaverse-app/ci-esta/compare/v1.3.0...v1.3.1) (2026-10-23)


### Bug fixes

* **actions:** derive planner runtimes from package metadata ([#88](https://github.com/gigaverse-app/ci-esta/issues/88)) ([1a93b6c](https://github.com/gigaverse-app/ci-esta/commit/1a93b6ca48b78a93e6c15d0bffda52f023d391e1))

## [1.3.0](https://github.com/gigaverse-app/ci-esta/compare/v1.2.0...v1.3.0) (2026-10-23)


### Features

* **timings:** add opt-in retained history adoption ([#86](https://github.com/gigaverse-app/ci-esta/issues/86)) ([cb12365](https://github.com/gigaverse-app/ci-esta/commit/cb12365d98ff4128d1dac0d86418708f06a3ea54))

## [1.2.0](https://github.com/gigaverse-app/ci-esta/compare/v1.1.4...v1.2.0) (2026-10-23)


### Features

* **timings:** share retained observation history ([#81](https://github.com/gigaverse-app/ci-esta/issues/81)) ([2615def](https://github.com/gigaverse-app/ci-esta/commit/2615def18d09f38e7377549286d770c78bb474a5))


### Bug fixes

* **branding:** restore CI-esta's Gantt banner ([b012d44](https://github.com/gigaverse-app/ci-esta/commit/b012d440303fe09ab932085fdddc6a9235f8c289))
* **ci:** preserve documentation skips after merge ([c376316](https://github.com/gigaverse-app/ci-esta/commit/c3763160b0a1a8e956b87bda86896a2e0e49caed))
* **ci:** select all runtime tests by declared dependencies ([9454e80](https://github.com/gigaverse-app/ci-esta/commit/9454e808977b7add231417fc687cb793eda8cc28))

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
