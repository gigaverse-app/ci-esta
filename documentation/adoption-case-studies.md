---
title: "When CI can be 10× faster and cost one-tenth as much"
description: "Three same-commit browser CI comparisons show 24× faster verdicts at one-twelfth the estimated runner cost. A second study measures the price of running every test faster."
---

# When CI can be 10× faster and cost one-tenth as much

The Gigaverse web team measured two decisions in the same Playwright workflow. **Does this revision need another browser run?** On unchanged nights, answering that question saved more than 90% of both wait and estimated cost. **How quickly can we run every journey when it does?** On a pull request, the team bought back nine minutes for about half a cent.

## When the last full checkpoint still covers the code

Every Sunday, the web app builds its mock app, starts a local server and emulator on each shard, and runs the deep browser suite. On Monday, CI-esta finds the last scheduled run whose browser jobs passed and whose completion marker was recorded. The app compares that revision with the current one. CI-esta’s test policy uses the result to decide whether to start the build and browsers. The reporting job still runs. An unchanged night leaves the previous checkpoint in place. [Scheduled baseline action](../actions/resolve-scheduled-base/action.yml) · [Test execution policy](../docs/test-execution-policy.md)

In each of the first three Sunday/Monday pairs in November 2026, both runs used the same commit and already used CI-esta. Sunday exercised the full-checkpoint policy and Monday exercised the affected-change policy. Each Monday’s planner log identified the preceding Sunday run as its baseline. All six runs passed. Times below run from workflow creation to the required check finishing, including queueing, planning and reporting.

| Full checkpoint / unchanged night | Time to green | Rounded Linux runner minutes | Estimated runner cost |
| --- | ---: | ---: | ---: |
| [Nov 1](https://github.com/gigaverse-app/gigaverse-web-app/actions/runs/41271376141) / [Nov 2](https://github.com/gigaverse-app/gigaverse-web-app/actions/runs/41386192513) | 15m 10s → 38s | 35 → 3 | 21.0¢ → 1.8¢ |
| [Nov 8](https://github.com/gigaverse-app/gigaverse-web-app/actions/runs/42445083082) / [Nov 9](https://github.com/gigaverse-app/gigaverse-web-app/actions/runs/42559515203) | 16m 20s → 40s | 39 → 3 | 23.4¢ → 1.8¢ |
| [Nov 15](https://github.com/gigaverse-app/gigaverse-web-app/actions/runs/43674892752) / [Nov 16](https://github.com/gigaverse-app/gigaverse-web-app/actions/runs/43801582232) | 16m 09s → 41s | 37 → 3 | 22.2¢ → 1.8¢ |

Across the three pairs, **2,859 seconds became 119 seconds (24.0× faster)** and **66.6¢ became 5.4¢ (91.9% lower estimated cost)**. The three rounded runner minutes on each unchanged night covered revision resolution, change detection and the required check. These comparisons measure the saving on a night eligible to skip. A weekly budget must also include the Sunday checkpoint and any weeknights with relevant changes. [Public timing and runner data for all six runs](../docs/benchmarks/2026-11-18-web-journeys.json)

## When all 16 browser journeys must run

For a change that needed browser coverage, the team profiled the build and each Playwright shard. A 16-vCPU runner built the app, then CI-esta’s balancer assigned whole spec files to five standard runners using recorded test durations. Local fixes also mattered. The same runner image could restore the pinned Firebase CLI, and the mock app stopped contacting live attestation services. The measured gain covers the combined changes. [Three-, four- and five-runner trial](https://github.com/gigaverse-app/gigaverse-web-app/pull/4481#issuecomment-6989299283) · [Firebase cache measurement](https://github.com/gigaverse-app/gigaverse-web-app/pull/4478#issuecomment-6987896775)

| Required PR workflow | Original run | Final run |
| --- | ---: | ---: |
| Elapsed time including queue and reporting | 14m 56s | 5m 30s |
| Build job | 4m 55s | 1m 12s |
| Longest Playwright step | 5m 41s | 2m 31s |
| Rounded minutes by runner class | 34 standard | 21 standard + 2 larger |
| Estimated runner cost | 20.4¢ | 21.0¢ |
| Matching test IDs passed once, with zero skips or retries | 16 | 16 |

That is **2.7× faster for 0.6¢ extra** on this pair of hosted runs. The required check now compares reported case IDs against the planned inventory. In replay it caught a missing shard report, an omitted test, a skipped test and a duplicate that preserved the total count. The original gate passed all four fixtures. [Combined benchmark](https://github.com/gigaverse-app/gigaverse-web-app/pull/4489#issuecomment-6989923184) · [Coverage check replay](https://github.com/gigaverse-app/gigaverse-web-app/pull/4489#issuecomment-6989749916)

## What to measure on your first PR

Pick one expensive workflow. For selection, compare a forced full run and an affected run on the same revision. Record which work legitimately skipped and why. For a faster execution strategy, compare the test identities and outcomes in both runs. In each experiment, measure time to the required verdict and total runner cost separately. Include planning, setup and per-job rounding. Your mix of unchanged and affected runs determines the overall return. [One-PR quickstart](../docs/quickstart.md) · [How to publish a measured comparison](../docs/measured-impact.md)

**Cost calculation.** Each successful job contributes its elapsed seconds rounded up to the next whole minute, multiplied by its runner rate. Skipped jobs contribute zero. The estimates here use $0.006/minute for standard Linux and $0.042/minute for the 16-vCPU build runner. Your runner rates, discounts and included minutes determine your bill. The public data records the run IDs, attempts, commits, timestamps and individual job durations. The original GitHub run and PR links require web-app repository access. [Public benchmark data](../docs/benchmarks/2026-11-18-web-journeys.json)
