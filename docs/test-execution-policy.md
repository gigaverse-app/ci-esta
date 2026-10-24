# Test execution policy and profiles

Status: implementation and consumer validation in progress. This design is part of
the unmerged execution-policy PR and requires Aviad's review before merge.

## Problem and ownership

Affected-test selection identifies work that a change can invalidate. It does not
decide whether a paid provider call, live broadcast, long benchmark, or deployed
smoke is appropriate on this occasion. Today AI, Backend, Due and Web implement
these decisions separately in selectors, workflow conditions and dispatch scripts.

CI-esta will own a portable admission contract and optional resource resolver.
pytest-selective and native selectors retain dependency analysis. Repositories
retain their tests, fixture setup, credentials, deployment configuration and
resource lifetimes. GitHub Actions retains scheduling and execution.

```text
BEFORE
  AI markers + labels ------> AI selector -------> runner / Kubernetes
  Due affected lanes -------> local conditions --> PostgreSQL / Redis suites
  Backend paths + dispatch -> local conditions --> runner / EKS / stress
  Web scope + /e2e ---------> local conditions --> Bun / Playwright / Artillery
                 each path owns admission and explains it differently

AFTER
  existing affected scope ----+
  occasion + explicit request +--> CI-esta policy --> explained immutable plan
  project profiles -----------+                          |
                                                        v
                              optional resource resolution / placement
                                                        |
                                                        v
                        existing repository executors and completion gates
                                                        |
                                                        v
                           CI-esta evidence and result reporting
```

## Migration contract

1. Extract behavior first and prove routing parity through actual entry points.
2. Add explicit profiles in a separate commit. Existing events keep their policy.
3. Scheduled or deployment probes execute fresh even for unchanged Git inputs.
4. An affected-scope fallback broadens work only within the permitted profile.
5. Invalid policy cannot produce a successful empty plan. Missing prerequisites
   are not passes, and deferred work is not described as unaffected.
6. Keep the CI-esta PR unmerged for human design review. Consumer PRs depend on
   its reviewed implementation and must not assume it is already in a release.

## Extraction sources

| Source | Reusable behavior | Consumer-owned behavior |
| --- | --- | --- |
| AI selector and resource plugin | lane request intersection, explicit scope, provider resolution, compatible placement, missing-resource diagnostics | OPT aliases, service images, namespaces, secret hydration |
| Due lane selection and comparison | complete suite admission and conformance-aware outcomes | Django variants, workers, guarantee validators, comparison workloads |
| Backend smoke and stress workflows | explicit admission, environment requirements | image provenance, database setup, EKS jobs, stress scenarios |
| Web E2E request and selection scripts | event normalization, trusted request context, fresh probes | Bun discovery, mock emulator, accounts, broadcast locking, Playwright/Artillery commands |
| CI-esta coverage and evidence actions | weekly/explicit policy pattern, strict completion, evidence reuse | repository-specific permitted occasions |

## Test plan

The executable schemas, action map, example configurations and routing evidence
are added alongside their implementation. The canonical schema comes from typed
models; examples are exercised through the shipped CLI and action, not prose tests.

- [ ] Preserve AI affected-by-lane routing, explicit paths, missing resources and placement.
- [ ] Preserve Due complete library/integration/comparison admission and validators.
- [ ] Preserve Backend normal checks and manual smoke/stress admission.
- [ ] Preserve Web mock/live distinctions, disabled workflows and shared-resource constraints.
- [ ] Exercise profile expansion, scheduled full scope, deployment freshness and explicit probes.
- [ ] Test unknown inputs, empty scope, invalid policy, unavailable resources and failed execution.
- [ ] Validate a non-Python command through the same planner and plan consumer.
- [ ] Open and link five PRs; verify Conventional Commit titles and required checks.
