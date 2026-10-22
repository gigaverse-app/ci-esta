# Closing the upstreaming gaps

The [original audit](adoption-audit.md) distinguished extraction from adoption.
These changes close its generic implementation gaps without moving application
credentials, deployment policy or conformance contracts into the toolkit.

| Capability | Durable implementation | Adoption / evidence |
| --- | --- | --- |
| Real dependency critical path | [PR 15](https://github.com/gigaverse-app/ci-esta/pull/15), source-workflow DAG, observed chain, execution CPM, slack and delay | CLI exercised against real runs; observer enabled in all four projects |
| Validated complete uv environment cache | PR 15, exact interpreter/platform/manifests/groups identity, broken-restore repair, locked sync | CI-esta plus [selective 27](https://github.com/gigaverse-app/pytest-selective/pull/27), [obligation 103](https://github.com/gigaverse-app/pytest-obligation/pull/103), [Due 82](https://github.com/gigaverse-app/due/pull/82) |
| Strict selected-lane aggregate gate | [PR 16](https://github.com/gigaverse-app/ci-esta/pull/16), shared action and workflow contract checker | All four retain always-run package/metadata checks and full/unknown-input execution |
| Conservative PR supersession | First PR attempts share a cancellation group; main, manual and reruns remain isolated | All four main workflows; Due widget workflow too |
| Runner capacity and local pools | [PR 14](https://github.com/gigaverse-app/ci-esta/pull/14), bounded global shard ranges, resource diagnostics and watchdog | Backend recipes preserved; small projects retain appropriate xdist/service isolation |
| Timing feedback | [PR 20](https://github.com/gigaverse-app/ci-esta/pull/20), `ci-esta-pytest learn`, reusable JUnit artifact action | [Executable tutorial](learned-test-timings.md), real pytest-to-planner regression and 1,050-test local execution; [selective 29](https://github.com/gigaverse-app/pytest-selective/pull/29), [Due 85](https://github.com/gigaverse-app/due/pull/85), [obligation 104](https://github.com/gigaverse-app/pytest-obligation/pull/104) |
| Backend rollout | Shared toolkit consumers | [AI 3109](https://github.com/gigaverse-app/gigaverse-ai/pull/3109) and [Backend 5495](https://github.com/gigaverse-app/gigaverse-backend/pull/5495) merged |

The gate validates completion; reports remain outside its dependency chain.
The repository rulesets now require `Validation gate` on each default branch;
Due also requires `Widget comparison gate`, in addition to its existing checks.
Duration hints and cached environments cannot authorize successful-lane reuse.
Whole-file sharding is available, but adding hosted jobs to short suites can cost
more than it saves. Due's crash/conformance and widget evidence retain their
existing validators. Application fixtures and external service state cannot be
inferred from Python imports alone.

See [critical paths](critical-path.md), [environment caching](environment-cache.md),
[selected gates](selected-gates.md), [runner pools](runners-and-diagnostics.md),
and [agent instructions](agents.md) for adoption, failure controls and boundaries.
