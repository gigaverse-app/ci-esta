![CI-esta: Let proven work rest. Measure the rest.](https://raw.githubusercontent.com/gigaverse-app/ci-esta/main/docs/assets/banner.png?v=e68364fbb504)

# CI-esta

Get your pull requests green sooner and spend less on GitHub Actions. CI-esta runs the checks your change needs, reuses passing results where it can, and splits the remaining tests across workers.

Free and open source under Apache 2.0. It runs in your existing workflows on hosted or self-hosted runners. You pay your usual runner costs.

## Try it on one pull request

Paste this into your coding agent from the root of your repository:

```text
Set up CI-esta in this repository. Fetch https://ci-esta.readthedocs.io/en/latest/agent-setup.md and follow it.
```

Your agent opens a pull request with the workflow changes and measurements. You can review which checks ran, how long you waited, and how much runner time they used.

[Quickstart](https://ci-esta.readthedocs.io/en/latest/docs/quickstart/) · [Adoption guide](https://ci-esta.readthedocs.io/en/latest/docs/tutorials/adoption-checklist/) · [GitHub Actions reference](https://ci-esta.readthedocs.io/en/latest/docs/actions/)

## What happens on your next push?

| When you… | CI-esta can… |
| --- | --- |
| Edit one function | Follow its dependencies and select the affected Python or Bun tests. |
| Push again after a passing run | Reuse a successful check when the recorded inputs and scope match. |
| Push a fix after a red run | [Re-run the tests that failed first](https://ci-esta.readthedocs.io/en/latest/docs/failed-first/), even when your fix does not touch them, and answer from one small batch if they still fail. |
| Change code covered only by unit tests | Skip unrelated lanes. A lane is a group of checks, such as database integration tests, that CI can run or reuse independently. |
| Install the same dependencies repeatedly | Restore a matching environment, check it and sync it with your lockfile. |
| Wait on the last slow shard | Use recorded test durations to balance work across parallel workers. |

The PR report shows what ran, what was reused and which job kept you waiting. Scheduled full runs exercise the complete suite.

## Follow a change through CI

Suppose you change how checkout rounds a discount. CI follows the changed code to the pricing and checkout tests. A database integration lane runs if its tests depend on the change. On your next push, a lane can reuse its earlier pass when its inputs still match. The PR report shows what ran again and why.

## Where can CI be 10× faster and cost one-tenth as much?

On three unchanged nights, CI-esta gave a browser workflow its verdict in **38–41 seconds**. Running its full checkpoint on those same commits took **15–16 minutes**. Across the three pairs that is **24× faster at 1/12 the estimated runner cost**, including the jobs that decide what to run. [See the six runs and cost calculation](https://ci-esta.readthedocs.io/en/latest/adoption-case-studies/).

When a change *did* need the browsers, the team cut the workflow from **14m 56s to 5m 30s**. All 16 journeys passed exactly once in both runs. The faster build and balanced shards cost an estimated **0.6¢ more** per run. [See the PR benchmark](https://ci-esta.readthedocs.io/en/latest/adoption-case-studies/#when-all-16-browser-journeys-must-run) · [Read the Django monorepo case study](https://ci-esta.readthedocs.io/en/latest/case-study/).

[Runner setup and diagnostics](https://ci-esta.readthedocs.io/en/latest/docs/runners-and-diagnostics/) · [All actions](actions/README.md) · [Contribute](CONTRIBUTING.md) · [License](LICENSE)

## Go deeper

- [Select affected tests](https://ci-esta.readthedocs.io/en/latest/docs/test-selection-policy/)
- [Reuse passing checks](https://ci-esta.readthedocs.io/en/latest/docs/evidence-reuse/)
- [Plan independent lanes](https://ci-esta.readthedocs.io/en/latest/docs/selected-gates/)
- [Cache environments](https://ci-esta.readthedocs.io/en/latest/docs/environment-cache/)
- [Balance test shards](https://ci-esta.readthedocs.io/en/latest/docs/learned-test-timings/)
- [Read the PR report](https://ci-esta.readthedocs.io/en/latest/docs/github-actions-observability/)

[Detailed adoption reference](ADOPTION-REFERENCE.md) — action recipes, execution profiles, benchmarks and evidence checks.

<details>
<summary>Project quality checks</summary>

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

<!-- pytest-quint-connect:start -->
<!-- pytest-quint-connect:contracts merged-pr-evidence -->
<!-- pytest-quint-connect:evidence 3aae06771ba6dfbf renderer 1.4.1 -->
<a href="https://github.com/gigaverse-app/pytest-quint-connect#impact"><picture><source media="(prefers-color-scheme: dark)" srcset="https://pytest-quint-connect-counter.gigaverse-oss.workers.dev/v1/sign.svg?key=cfe8d51e3678507c54e1b07ca48075c79bc0ce43b98f12b051d8d66f002901c9&amp;name=gigaverse-app%2Fci-esta&amp;theme=dark"><img alt="What pytest-quint-connect&#x27;s contracts caught in gigaverse-app/ci-esta&#x27;s pull requests" src="https://pytest-quint-connect-counter.gigaverse-oss.workers.dev/v1/sign.svg?key=cfe8d51e3678507c54e1b07ca48075c79bc0ce43b98f12b051d8d66f002901c9&amp;name=gigaverse-app%2Fci-esta" width="100%"></picture></a>

<a href="https://github.com/gigaverse-app/pytest-quint-connect" title="Mutants are planted fake bugs: deliberately broken copies of the code, used only during this test run. Each must make some history diverge, proving the tests are meaningful: they would notice that kind of bug"><img alt="Quint contracts: 1 contract passed · 106 histories · 3/3 mutants caught" src="https://img.shields.io/badge/Quint_contracts-1_contract_passed_%C2%B7_106_histories_%C2%B7_3%2F3_mutants_caught-brightgreen"></a>

<details>
<summary>✅ 1 contract · 110/110 cases · 3/3 mutants caught · 106 histories</summary>

| | <img width="2000" height="1" align="right" alt="">Contract | Cases passed | [Mutants caught](https://github.com/gigaverse-app/pytest-quint-connect/blob/v1.4.1/docs/why.md#proof-that-the-tests-can-fail "Mutants are planted fake bugs: deliberately broken copies of the code, used only during this test run. Each must make some history diverge, proving the tests are meaningful: they would notice that kind of bug") |
| :-: | :-- | --: | --: |
| ✅ | `merged-pr-evidence` `merged_pr/test_merged_pr_contract.py::test_merged_pr`<br><sub>106 histories (6 witnesses, 100 samples, seed 17) · every action covered · Quint 0.33.1</sub> | 110/110 | 3/3 |

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
- `automatic`: Use automatic discovery with whole-workflow completion before merge

**Invariant** `safety`, checked while sampling histories.

**Witnesses**, scenarios replayed exactly as written: `contractRecoveryTest`, `contractOpenTest`, `contractLastTest`, `contractInvalidTest`, `contractAutomaticTest`, `contractAutomaticLateTest`.

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

</details>
