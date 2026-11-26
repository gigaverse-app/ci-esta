---
title: Making the Riemann Hypothesis proof faster to work on
description: How CI-esta cut a Lean proof job from 234 to 110 seconds, and what a separate Lake benchmark tells us about speeding up proof development.
---

# Making the Riemann Hypothesis proof faster to work on

On November 20, 2026, Levent Alpöge released a Lean formalization of a proof of the Riemann Hypothesis, found working with Claude. The hypothesis dates to 1859 and concerns the zeros of the zeta function, which are tied to the distribution of prime numbers. The next day, the Lean FRO and Mathlib Initiative published their verification statement. They checked that the formal theorem was the intended statement and reported that Lean’s kernel and independent proof checkers accepted the proof export. [Alpöge’s announcement](https://alpo.ge/remark.pdf) · [Lean community verification](https://leanprover-community.github.io/blog/posts/riemann-hypothesis/) · [Clay Mathematics Institute background](https://www.claymath.org/millennium/riemann-hypothesis/)

The formalization opened a second phase of work in public. On November 25, the community repository moved its cleanup to the condensed edition from `lsernau/grh-lean`. Now researchers can trace why a lemma is needed, and contributors can clarify a definition, untangle imports, or move a useful result into Mathlib. The easier it is to build and check a change, the more people can take part, including contributors who came to help with tooling. [Community repository and contribution goals](https://github.com/leanprover-community/riemann-hypothesis) · [Readable edition](https://github.com/lsernau/grh-lean)

In one Riemann Hypothesis CI replay, restoring Mathlib took **124 seconds** and `lake build` took **6 seconds**. A fresh runner was spending two minutes on Mathlib alone before it could reach the proof build. With a prehydrated dependency seed, the same proof and axiom checks finished **124 seconds sooner**. [Paired GitHub Actions replay](https://github.com/aviadr1/riemann-hypothesis/actions/runs/45881900524)

## What a green proof job means

Lean checks the formal proof. Lake is Lean’s build tool and package manager. It resolves packages, tracks which modules depend on each other, and reuses build artifacts when their inputs still match. Continuous integration runs those tools against the revision under review and gives contributors a shared record of what passed. [Lake reference](https://lean-lang.org/doc/reference/latest/Build-Tools-and-Distribution/Lake/)

In the Riemann project, the required `lake build` job also fails on warnings that a declaration uses `sorry`, Lean’s proof placeholder. It checks the axiom dependencies of five theorems against `propext`, `Classical.choice`, and `Quot.sound`. The project also uses Comparator to compare the statements with a separate challenge file and check the proof with Lean’s kernel and nanoda. The benchmark below measures the build job through its axiom check. [Build workflow](https://github.com/leanprover-community/riemann-hypothesis/blob/c5451bd3ba92480e05c4218f5221bb2900c58706/.github/workflows/build.yml) · [Statements and Comparator checks](https://github.com/leanprover-community/riemann-hypothesis#theorem-statements)

## How CI-esta saves the dependency work

CI-esta runs inside GitHub Actions. Its completed-run report reads job and step timings from GitHub so you can see whether setup, compilation or validation dominates. We ran that observer on the Lake benchmark too. The report runs after the work it measures. For Riemann, the timing split pointed to the cost of preparing a fresh runner, so we built an action that reuses the prepared dependency tree. [Workflow reporting guide](../docs/github-actions-observability.md) · [Lake timing report](https://github.com/aviadr1/riemann-hypothesis/actions/runs/45882949920)

1. A runner operator builds a **read-only seed** from a trusted checkout of the project. In this case it contains the pinned Lean toolchain, the dependency checkouts, and their available compiled artifacts.
2. At checkout, `restore-lean-packages` compares `lean-toolchain`, `lakefile.toml`, and `lake-manifest.json` byte for byte and checks the pinned Git revisions of the seeded packages. A missing seed, mismatched input or unsuccessful restore takes the existing dependency setup path.
3. On a hit, the action copies the packages into the job’s own `.lake/packages`. On a reflink-capable filesystem such as Btrfs, the private copy can share data blocks with the seed until a write. With toolchain linking enabled, Elan can use the preinstalled compiler and Lake gets a writable artifact cache in the workspace by default.
4. The project still checks Tau Ceti’s Mathlib pin and its restrictions on imports in the proof statements. Lake can fetch anything missing from the current dependency graph. The project restores its own build cache, runs `lake build`, and checks the five theorems’ axioms.

The seed belongs to the runner operator, and each job gets its own writable workspace. That matters when the pipeline checks contributions from forks. The action ships in CI-esta 1.34.0, and the Riemann adoption PR documents how to provision the seed on the project’s runners. [Lean seed setup guide](../docs/lean-packages.md) · [CI-esta 1.34.0](https://github.com/gigaverse-app/ci-esta/releases/tag/v1.34.0) · [Riemann adoption PR](https://github.com/leanprover-community/riemann-hypothesis/pull/8719)

## From 234 seconds to 110 seconds

On November 26, we replayed the same batch proof source on two GitHub-hosted Linux jobs with Btrfs workspaces and fresh job homes. Both verified the same `src` Git tree and passed the build and all five axiom checks. An earlier series ran four replays per input in each mode. It included a small source PR alongside the batch. [Paired replay](https://github.com/aviadr1/riemann-hypothesis/actions/runs/45881900524) · [Four-replay series](https://github.com/aviadr1/riemann-hypothesis/actions/runs/45878587436)

| Riemann proof workload | Fresh dependency setup | Seeded dependencies | Speedup |
| --- | ---: | ---: | ---: |
| Batch proof, paired replay | 234 s | 110 s | 2.13× |
| Source PR, median of four replays per mode | 272 s | 123.5 s | 2.20× |
| Batch proof, median of four replays per mode | 263 s | 129 s | 2.04× |

Times run from the start of checkout to the end of the axiom check. In the paired replay, the seed restore took 13 seconds and the Mathlib download step could be skipped. Both jobs used the project’s existing build cache and `lake build` took 6 seconds in each. Preparing the seed took 195 seconds once, outside the measured interval, which also excludes queue time. An ext4 trial took about 49 seconds to restore the seed, illustrating why filesystem choice matters. Actual pull-request latency also depends on runner capacity, the seed hit rate, and how much Lean must recompile. [Cold job steps](https://github.com/aviadr1/riemann-hypothesis/actions/runs/45881900524/job/140123023845) · [Seeded job steps](https://github.com/aviadr1/riemann-hypothesis/actions/runs/45881900524/job/140123023446) · [Ext4 trial](https://github.com/aviadr1/riemann-hypothesis/actions/runs/45880469629)

We also checked what happens when the seed is missing and when a proof is invalid. The first run fetched dependencies through the normal path. In the second, the seed restore succeeded and `lake build` still rejected the invalid proof. A separate replay passed the build and axiom checks and uploaded the cache artifact used by the merge-queue workflow. [Missing-seed run](https://github.com/aviadr1/riemann-hypothesis/actions/runs/45879474875) · [Invalid-proof control](https://github.com/aviadr1/riemann-hypothesis/actions/runs/45880469629) · [Cache staging replay](https://github.com/aviadr1/riemann-hypothesis/actions/runs/45880765174)

## How much faster can Lake itself get?

When the package artifacts are already on disk, setup and compilation still have costs of their own. Lake computes which transitive imports a module needs and where their artifacts live. Lean’s upstream `inundation` benchmark can exercise this work in isolation by computing module setups against a prebuilt import graph. [Upstream benchmark](https://github.com/leanprover/lean4/pull/16083)

We built two Lake binaries from the Lean 4.37.0-rc1 sources and changed the candidate to track visited imports with hash sets. On a fixture that requested 1,080 module setups, we alternated the order of the two binaries for eight pairs on the same runner. Median wall time fell from **2.38 to 2.15 seconds**, about **10%**, while median peak memory rose about **6%**. That is a tradeoff to check on real Lean projects before proposing a Lake change. The Riemann adoption PR uses the released Lake toolchain and its CI speedup comes from dependency setup. [Lake experiment and all 16 measurements](https://github.com/aviadr1/riemann-hypothesis/actions/runs/45883970283/job/140129973292) · [Experiment workflow](https://github.com/aviadr1/riemann-hypothesis/blob/440920045b4c812ee593c0e6772c7a4aeba8846b/.github/workflows/lake-import-sets.yml)

The same investigation turned up two smaller ways to help upstream. A dry-lint scan of Lake’s Lean sources rated two unrelated multiline strings as identical. That false match led to a merged fix. A selective-deps probe also showed that changing a Lake test fixture could select its reader, while changing a shared shell helper selected both tests in the probe. That gives maintainers a concrete way to try narrower CI for fixture-only edits. [Merged dry-lint fix](https://github.com/gigaverse-app/dry-lint/pull/202) · [Lake fixture dependency probe](https://github.com/aviadr1/riemann-hypothesis/actions/runs/45883619457)

## Where another contributor can help

If you want to help with the Riemann formalization, start with the project’s open issues. A clearer lemma, a smaller import tree, or a reproducible CI bottleneck gives reviewers something concrete to work with. Use the community repository’s contribution guidance to choose a change that helps maintain the proof. [Riemann Hypothesis issues](https://github.com/leanprover-community/riemann-hypothesis/issues) · [Project guidance](https://github.com/leanprover-community/riemann-hypothesis#riemann-hypothesis)

If you maintain a Lean project, pick a representative proof change and measure its path to a verdict. Record runner wait and setup separately, and keep the full proof checks in both runs. If dependency hydration dominates, try a trusted seed and compare a hit with a fresh job. If module setup or proof elaboration dominates, use a warm workspace to isolate the repeated work and bring that benchmark upstream. Share the revision, toolchain, runner, and run links so the next contributor can repeat the experiment. [Measure your CI critical path](../docs/tutorials/measure-critical-path.md) · [Prehydrate Lean dependencies](../docs/lean-packages.md)

The landmark result brought a large proof into a form people could check together. Shorter, reproducible feedback gives more of those people time to make it easier for the next person to understand.
