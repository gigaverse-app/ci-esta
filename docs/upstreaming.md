# Extraction boundary and adoption

CI-esta consolidates the language-independent CI toolkit in one repository. The initial extraction includes six actions, reporting models/renderers/API client, shared test-selection reporting, and compatibility enrichment profiles. Source history remains in backend-common; [provenance](../PROVENANCE.md) records the extracted revision and paths.

## Shipped here

The complete action catalog, pytest execution/evidence and hygiene helpers, image measurement and live CI drill are now in this project. [The inventory](migration-inventory.json) maps each source path to its canonical owner. The distribution is `ci-esta`, the import namespace is `ci_esta`, and JavaScript helpers remain GitHub Actions assets rather than an npm package.

The optional dependency-token adapter preserves backend-common retag normalization. A retag can reuse positive evidence only when the dependency tree is identical; unreadable or ambiguous dependencies retain exact-pin or full-validation fallbacks. Manual reruns never reuse lane evidence.

## Ownership retained elsewhere

pytest-selective owns impact graphs, selection, shard planning and type-check scope. CI-esta calls that pinned package. pytest-obligation owns durable-work conformance. Application/Kafka helpers, service instrumentation, release tagging, consumer bump automation, and deployment policy remain in backend-common. Repository workflows compose upstream actions while retaining repository event and publication policy.

## Consumer migration

[backend-common PR269](https://github.com/gigaverse-app/backend-common/pull/269) replaces implementation copies with module aliases and immutable action delegation. Existing imports and action paths are preserved. Direct support-file compatibility imports need the pinned Python package installed; Actions callers use the delegated upstream runtime. Consumer adoption is verified through the generated backend/AI bump PRs, not a blanket claim that every downstream repository has migrated.

## Discoverability

The documentation follows patterns from Due and pytest-obligation: a concrete failure/problem in the introduction, runnable adoption examples, a page explaining what green means, explicit limitations, task-oriented documentation links, and comparison pages that help a real choice. README text and repository topics describe GitHub Actions optimization, CI observability and evidence reuse. Cross-project links explain an actual relationship instead of implying all four tools are required.

No ranking or traffic improvement is claimed. Package publication is a separate step after release readiness; placeholder packages are not used to reserve names.
