![CI-esta: Let proven work rest. Measure the rest.](https://raw.githubusercontent.com/gigaverse-app/ci-esta/main/docs/assets/banner.png?v=e68364fbb504)

# CI-esta: make GitHub Actions faster, with evidence

**Set it up with your coding agent.** Give Claude Code, Codex, Cursor or any coding agent in your repository this
one prompt:

```text
Set up CI-esta in this repository. Fetch https://ci-esta.readthedocs.io/en/latest/agent-setup.md and follow it.
```

The agent checks your repository's conventions (required check, action pinning, AI policy, tox/nox/uv), measures
completed runs, makes one change the numbers support, proves it on the same commit with an unchanged test inventory
and a failing probe, and opens a draft pull request. Merging, required checks, runner groups and secrets stay with
you. To do it by hand, start with the [quickstart](docs/quickstart.md) or
[measure your first run](docs/tutorials/measure-critical-path.md).

See the [selection and evidence policy](docs/test-selection-policy.md) for the scenario map, tested Git identities, reruns and Python/JavaScript setup.

[![Documentation](https://readthedocs.org/projects/ci-esta/badge/?version=latest)](https://ci-esta.readthedocs.io/en/latest/)

[Read the documentation](https://ci-esta.readthedocs.io/en/latest/) · [Related tools](https://ci-esta.readthedocs.io/en/latest/ecosystem/)

See what holds up your PR, avoid repeating validated work, and run the remaining
tests efficiently. CI-esta adds reports, environment caching, reusable execution
evidence and test scheduling to your existing GitHub Actions workflows. No account,
hosted service or application-language change is required.

[![CI](https://github.com/gigaverse-app/ci-esta/actions/workflows/ci.yml/badge.svg)](https://github.com/gigaverse-app/ci-esta/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/ci-esta)](https://pypi.org/project/ci-esta/)
[![Apache-2.0](https://img.shields.io/badge/license-Apache--2.0-blue)](LICENSE)

## Choose your first improvement

Use the [adoption tutorial and checklist](docs/tutorials/adoption-checklist.md)
to choose an order, verify each improvement and find every action/CLI capability.
Run `ci-esta adoption --root .` for a read-only inventory with source-linked
suggestions. It helps find gaps; successful hosted runs and measurements verify
whether an integration is useful.

| Your problem | What you gain | Start here |
| --- | --- | --- |
| You need to show whether an optimization helped | Verified before/after gate, runner and step comparisons tied to exact source runs | [Measured impact](docs/measured-impact.md) |
| You cannot tell what keeps a PR waiting | A sticky report with gate latency, dependency critical path, step timings and runner usage | [Report one workflow](docs/quickstart.md#report-a-completed-workflow) |
| Jobs reinstall the same dependencies | A validated environment restore that repairs broken caches and always synchronizes the lock | [Replace your setup steps](docs/quickstart.md#cache-your-python-environment) |
| Unaffected tests start expensive services | Python file or whole-job selection before setup, with explanations | [Add pytest-selective](https://github.com/gigaverse-app/pytest-selective) |
| A new revision repeats work that already passed | Reuse a matching completed lane, including a passing lane from a workflow where another lane failed | [Evidence reuse](docs/evidence-reuse.md) |
| One test shard keeps everyone waiting | Learn file costs from JUnit; balance work inside one larger runner, across runners, or both | [Runnable shard recipe](examples/pytest-shards/README.md) |
| Missing shard results could look green | Verify completion receipts and require every planned pool before passing the gate | [Completion and gates](docs/ci-optimization.md#close-the-timing-feedback-loop) |
| Tests hang or use less CPU than expected | Process/thread diagnostics, cgroup limits and live shard progress | [Runner diagnostics](docs/runners-and-diagnostics.md#resource-and-pytest-diagnostics) |

## Start with one action

In an existing uv test job, keep checkout and your test command. Replace Python
setup, uv setup and dependency installation with:

```yaml
- uses: actions/checkout@v7
- uses: gigaverse-app/ci-esta/actions/setup-cached-uv@v1
  with:
    python-version: '3.12'
    sync-args: '--group test'
- run: uv run --no-sync pytest
```

Use your project's interpreter and dependency groups. Every action lives under
`actions/NAME`. Use `gigaverse-app/ci-esta/actions/ci-observability@v1` for reports.

Use `actions/NAME@v1` for automatic Actions API upgrades. That alias is
independent of Python package versions. Older `.github/actions/NAME` and top-level
named callers must migrate to `actions/NAME`; each action has one implementation.
[Action API and versioning](docs/actions.md).

[Copy the complete reporting or cache workflow](docs/quickstart.md). The actions
set up their own tools; using them does not require adding CI-esta to your app.
For Python execution commands and plugins, install `ci-esta[pytest]` in the test
environment. Reporting and evidence actions also work with non-Python projects;
[Bun users have a native selection adapter](docs/bun-test-selection.md).

## Agent setup in depth

The one prompt above fetches [the agent setup procedure](skills/ci-esta/SKILL.md),
published byte for byte at `agent-setup.md` with an [`llms.txt`](https://ci-esta.readthedocs.io/en/latest/llms.txt)
index. To install it as a skill instead, see [agent skill installation](docs/agents.md).
Updating the Python package does not update an installed agent skill.

## Results you can inspect

| Change | Observed result | Evidence |
| --- | --- | --- |
| Route a README change with pytest-selective | 627 → 48 runner-seconds; 211 → 26 seconds elapsed | [Matched selection runs](https://github.com/gigaverse-app/pytest-selective/blob/main/docs/benchmarks/2026-10-22-routing.md) |
| Optimize a full conformance suite's execution | Required gate 538 → 282 seconds, retaining all 982 integration cases per variant and validators | [Full execution comparison](docs/benchmarks/2026-10-23-critical-execution.md) |
| Remove Windows Git startup overhead | Full gate 249 → 185 seconds with existing cases, platform matrix and coverage retained | [Fresh control and raw reports](docs/benchmarks/2026-10-23-windows-saleor.md) |

These are scenario-specific observations. Selection savings belong to
pytest-selective and the consumer's declared inputs; they are not receipt-reuse
savings. Runner-seconds are summed execution, not a billing invoice. Measure your
own cold/warm setup, full/selected runs and runner layouts before claiming a gain.

## How the safeguards fit

A duration estimate changes where a test runs, never whether it belongs in the
plan. An environment cache accelerates setup; locked synchronization still runs.
A completion receipt can justify reusing the same declared work, but an old green
workflow alone cannot. Missing or contradictory proof executes the work again.
Explicit reruns and scheduled full checks retain their meaning.

Input declarations, service isolation and conformance requirements belong to your
project. [Evidence reuse](docs/evidence-reuse.md) and [strict gates](docs/selected-gates.md)
explain these boundaries. The [optimization guide](docs/ci-optimization.md) connects
selection, timing feedback, execution and measurement in order.

## Further documentation

- [Public actions](docs/actions.md) and [full toolkit catalog](actions/README.md)
- [Critical path and slack](docs/critical-path.md), [cost reporting](docs/github-actions-observability.md), and [environment caching](docs/environment-cache.md)
- [Learned timings](docs/learned-test-timings.md), [runner pools](docs/runners-and-diagnostics.md), and [Python CI tuning](docs/python-ci-tuning.md)
- [Integrations](docs/integrations.md), [alternatives](docs/alternatives.md), and [revision-bound adoption audit](docs/adoption-audit.md)
- [Contributing](CONTRIBUTING.md), [releases](RELEASING.md), and [source provenance](PROVENANCE.md)

Install the CLI with `uv tool install --upgrade --refresh 'ci-esta[selection]>=1.11,<2'` (Python 3.11+);
`--refresh` lets uv see a release published in the last few minutes, and `ci-esta --version` confirms which
release is on `PATH`.
Base reporting alone (`pip install ci-esta`) needs neither pytest nor pytest-selective.
For fixtures, schemas, source scanners, and subprocess helpers, follow the
[pytest-selective sidecar tutorial](https://github.com/gigaverse-app/pytest-selective/blob/main/docs/tutorials/sidecar-dependencies.md).
Declare inputs at their readers so unrelated documentation does not select tests.

Use `ci-esta[selection]` for Python selection reports or `ci-esta[pytest]` for
pytest execution tools. Before 1.0, review each minor release's migration notes.

### Test execution profiles

Separate affected work from special-occasion execution with [test execution policy](docs/test-execution-policy.md). The JSON planner works with pytest, Bun, Playwright and custom runners; resource resolution is optional.

New policy adopters can declare work directly in `plan-test-policy` without a
policy file. CI-esta provides ordinary, full, weekly, smoke, performance and probe
defaults. Optional configuration contains only exceptional metadata and profile
overrides; existing selectors remain authoritative for work IDs.

<!-- dry-lint-progress:start -->
<a href="https://github.com/gigaverse-app/dry-lint"><picture><source media="(prefers-color-scheme: dark)" srcset="https://dry-lint-counter.gigaverse-oss.workers.dev/v1/sign.svg?theme=dark&amp;key=cfe8d51e3678507c54e1b07ca48075c79bc0ce43b98f12b051d8d66f002901c9&amp;name=gigaverse-app%2Fci-esta&amp;cleaned=20&amp;remaining=0&amp;dismissed=0"><img alt="dry-lint in gigaverse-app/ci-esta: new duplicates kept out of its pull requests, 20 old duplicates cleaned up, 0 remaining" src="https://dry-lint-counter.gigaverse-oss.workers.dev/v1/sign.svg?key=cfe8d51e3678507c54e1b07ca48075c79bc0ce43b98f12b051d8d66f002901c9&amp;name=gigaverse-app%2Fci-esta&amp;cleaned=20&amp;remaining=0&amp;dismissed=0" width="100%"></picture></a>

**Reviewed duplication debt** · Counts from the committed baselines.

| Accepted pairs | Remaining | Retired | Dismissed |
| :-- | --: | --: | --: |
| Functions | 0 | 20 | 0 |
| Models | Not initialized | — | — |

[Accepted backlog](.dry-lint/baseline.json) · [Weekly audit](https://github.com/gigaverse-app/ci-esta/actions/workflows/dry-lint-audit.yml)

Retired means a side was removed, or (functions only) the judge now finds the pair separate. It is not a count of refactors. Dismissals stay separate; an uninitialized model baseline is unknown.
<!-- dry-lint-progress:end -->

## Model-connected evidence checks

The [merged-PR evidence contract](https://github.com/gigaverse-app/ci-esta/blob/main/docs/merged-pr-evidence.md)
replays a Quint lifecycle model through the actual collector and timing store.

<!-- pytest-quint-connect:start -->
<!-- pytest-quint-connect:contracts merged-pr-evidence -->
<!-- pytest-quint-connect:evidence 9e73f61f843a1c9e renderer 1.4.1 -->
<a href="https://github.com/gigaverse-app/pytest-quint-connect#impact"><picture><source media="(prefers-color-scheme: dark)" srcset="https://pytest-quint-connect-counter.gigaverse-oss.workers.dev/v1/sign.svg?key=cfe8d51e3678507c54e1b07ca48075c79bc0ce43b98f12b051d8d66f002901c9&amp;name=gigaverse-app%2Fci-esta&amp;theme=dark"><img alt="What pytest-quint-connect&#x27;s contracts caught in gigaverse-app/ci-esta&#x27;s pull requests" src="https://pytest-quint-connect-counter.gigaverse-oss.workers.dev/v1/sign.svg?key=cfe8d51e3678507c54e1b07ca48075c79bc0ce43b98f12b051d8d66f002901c9&amp;name=gigaverse-app%2Fci-esta" width="100%"></picture></a>

<a href="https://github.com/gigaverse-app/pytest-quint-connect" title="Mutants are planted fake bugs: deliberately broken copies of the code, used only during this test run. Each must make some history diverge, proving the tests are meaningful: they would notice that kind of bug"><img alt="Quint contracts: 1 contract passed · 104 histories · 3/3 mutants caught" src="https://img.shields.io/badge/Quint_contracts-1_contract_passed_%C2%B7_104_histories_%C2%B7_3%2F3_mutants_caught-brightgreen"></a>

<details>
<summary>✅ 1 contract · 108/108 cases · 3/3 mutants caught · 104 histories</summary>

| | <img width="2000" height="1" align="right" alt="">Contract | Cases passed | [Mutants caught](https://github.com/gigaverse-app/pytest-quint-connect/blob/v1.4.1/docs/why.md#proof-that-the-tests-can-fail "Mutants are planted fake bugs: deliberately broken copies of the code, used only during this test run. Each must make some history diverge, proving the tests are meaningful: they would notice that kind of bug") |
| :-: | :-- | --: | --: |
| ✅ | `merged-pr-evidence` `merged_pr/test_merged_pr_contract.py::test_merged_pr`<br><sub>104 histories (4 witnesses, 100 samples, seed 17) · every action covered · Quint 0.33.1</sub> | 108/108 | 3/3 |

</details>

<details>
<summary>🧪 3 mutants (planted fake bugs), all caught</summary>

| Contract | [Mutant](https://github.com/gigaverse-app/pytest-quint-connect/blob/v1.4.1/docs/why.md#proof-that-the-tests-can-fail "Mutants are planted fake bugs: deliberately broken copies of the code, used only during this test run. Each must make some history diverge, proving the tests are meaningful: they would notice that kind of bug") | <img width="2000" height="1" align="right" alt="">What it breaks | Caught by | At |
| :-- | :-- | :-- | :-- | :-- |
| `merged-pr-evidence` | `open-admission` | Admit an unmerged PR as though it merged after validation | `witness-contractOpenTest`<br><sub>samples: 1/100 diverge</sub> | state 5, after `stage()` |
| `merged-pr-evidence` | `older-green` | Select the oldest successful run instead of the last admitted run | `witness-contractLastTest`<br><sub>samples: 0/100 diverge</sub> | state 7, after `stage()` |
| `merged-pr-evidence` | `dropped-publication` | Lose the admitted observation during history publication | `witness-contractRecoveryTest`<br><sub>samples: 0/100 diverge</sub> | state 11, after `publish()` |

</details>

<details open>
<summary>What <code>merged-pr-evidence</code> says</summary>

**Actions**, and the code each one drives:

- `init`: New HTTP boundary and real collector/history
- `push`: GitHub changes PR head
- `start`: GitHub admits a producer run
- `passGate`: GitHub records successful gate completion
- `finish`: GitHub completes producer
- `upload`: GitHub exposes measured-only artifact
- `expire`: GitHub expires artifact
- `closePR`: GitHub closes without merging
- `merge`: GitHub records merge cutoff
- `stage`: MergedPRTimingCollector.stage
- `publish`: publish_promotion
- `crash`: Discard local staging; keep published history
- `inspect`: Read staged source and published observations without mutation

**Invariant** `safety`, checked while sampling histories.

**Witnesses**, scenarios replayed exactly as written: `contractRecoveryTest`, `contractOpenTest`, `contractLastTest`, `contractInvalidTest`.

**Bounds**: seed `17` · max_samples `500` · max_steps `35` · n_traces `100`.

**Witness `contractRecoveryTest`, step by step**: the observation the model starts from, then what it expects each action to change.

| State | Action | Model expects |
| --: | :-- | :-- |
| `0` | `init()` | `{ published: Set(), staged: 0 }` |
| `1` | `start()` | unchanged |
| `2` | `passGate(r=1)` | unchanged |
| `3` | `merge()` | unchanged |
| `4` | `stage()` | unchanged |
| `5` | `finish(r=1, value='success')` | unchanged |
| `6` | `upload(r=1, value='valid')` | unchanged |
| `7` | `stage()` | `staged: 0 → 1` |
| `8` | `crash()` | `staged: 1 → 0` |
| `9` | `stage()` | `staged: 0 → 1` |
| `10` | `expire(r=1)` | unchanged |
| `11` | `publish()` | `published: Set() → Set(1)` |
| `12` | `publish()` | unchanged |
| `13` | `inspect()` | unchanged |

</details>

<sub>Generated by [pytest-quint-connect](https://github.com/gigaverse-app/pytest-quint-connect) from contract receipts; [what a passing run proves](https://github.com/gigaverse-app/pytest-quint-connect/blob/v1.4.1/docs/limits.md).</sub>
<!-- pytest-quint-connect:end -->
