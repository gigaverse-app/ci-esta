# Extraction boundary and adoption

CI-esta consolidates the language-independent CI toolkit in one repository. The initial extraction includes six actions, reporting models/renderers/API client, shared test-selection reporting, and compatibility enrichment profiles. Source history remains in backend-common; [provenance](../PROVENANCE.md) records the extracted revision and paths.

## Shipped here

`ci-observability`, `collect-pr-changes`, `resolve-incremental-pr-base`, `resolve-lane-evidence`, `validation-gate`, and `publish-prometheus-snapshot` are under `.github/actions/`. The Python package is `ci_esta`; the distribution and CLI are `ci-esta`. JavaScript helpers are used directly by GitHub Actions and are not published as an npm package.

The lane resolver compares dependency pins exactly. It intentionally omits the private backend-common retag normalization and dependency-token requirement. A changed pin reruns a lane even when the two revisions happen to contain the same tree.

## Remaining source tools

These are candidates for later additions to this same project, not promised APIs in the alpha:

- Stale-rerun admission/cancellation and coverage scheduling policies.
- CI definition linting and security-scan composition.
- Docker/image evidence and ECR image reuse, with provider-specific adapters.
- Workflow policy checks and the configurable parts of the live CI drill harness.

pytest selection, sharding and typecheck scope belong to pytest-selective. Python fixture-expansion, canary and exhaustive-completion proof need their own pytest-specific ownership review; pytest-obligation's durable-work conformance purpose should not be diluted into a generic pytest utilities package. Runtime application instrumentation remains in backend-common.

## Consumer migration

Existing backend-common consumers are not automatically repointed by this extraction. Review action permissions, use immutable CI-esta revisions, adopt measurement first, and only then enable narrower evidence inputs. Run a representative full validation and failure/retry sequence before replacing required checks. Keep source consumer adapters until each migration is verified; avoid maintaining independent fixes in both implementations.

## Discoverability

The documentation follows patterns from Due and pytest-obligation: a concrete failure/problem in the introduction, runnable adoption examples, a page explaining what green means, explicit limitations, task-oriented documentation links, and comparison pages that help a real choice. README text and repository topics describe GitHub Actions optimization, CI observability and evidence reuse. Cross-project links explain an actual relationship instead of implying all four tools are required.

No ranking or traffic improvement is claimed. Package publication is a separate step after release readiness; placeholder packages are not used to reserve names.
