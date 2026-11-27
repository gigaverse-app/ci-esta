---
title: How a 2× faster CI replay could help people work on the Riemann Hypothesis proof
description: A landmark proof became a public Lean project. In a replay on GitHub-hosted runners, a prehydrated dependency seed cut the build and axiom check from 234 to 110 seconds, excluding queue time. The change is proposed upstream.
---

# How a 2× faster CI replay could help people work on the Riemann Hypothesis proof

In 1859, Bernhard Riemann posed a conjecture about the zeros of the zeta function, which are tied to the distribution of prime numbers. On November 20, 2026, 167 years later, Levent Alpöge released a Lean formalization of a proof he found working with Claude. The release filled more than 175,000 files and about 17 million lines of Lean. The next day, the Lean FRO and Mathlib Initiative reported that the theorem matched Mathlib’s vetted statement and that Lean’s kernel and independent checkers accepted the proof export. [Alpöge’s announcement](https://alpo.ge/remark.pdf) · [Verification statement](https://leanprover-community.github.io/blog/posts/riemann-hypothesis/) · [Archive and independent checks](https://math.mit.edu/~drew/grh/) · [Mathematical background](https://www.claymath.org/millennium/riemann-hypothesis/)

## A proof people can work on together

The community’s next task was to make the formal proof easier to study, teach, and build on. On November 25, the community repository moved its cleanup to the condensed edition from `lsernau/grh-lean`. That work is public, and it gives people with different skills a place to start. [Community repository and contribution goals](https://github.com/leanprover-community/riemann-hypothesis) · [Readable edition](https://github.com/lsernau/grh-lean)

- A mathematician can trace where a lemma enters the argument and explain why it matters.
- A Lean contributor can simplify a proof, clarify a definition, or move a reusable result into Mathlib.
- A tooling contributor can reduce repeated setup, improve a linter, or find out why a build is slow.

All three benefit from a quick answer to the same question. Does this revision still check? In one paired replay on GitHub-hosted runners in a fork, a job with CI-esta’s prehydrated dependencies took **110 seconds** from checkout through the axiom checks, against **234 seconds** for a fresh job. The fresh runner had spent **124 seconds** restoring Mathlib alone. Those times leave out queueing and the 195 seconds spent preparing the seed once. The project has not adopted the change, and we have not measured it on the project’s own runners. [Paired GitHub Actions replay](https://github.com/aviadr1/riemann-hypothesis/actions/runs/45881900524)

## What reviewers can learn from a passing check

Say a contributor removes an import that looks unnecessary. Reviewers can inspect the diff, and CI runs Lake to check the resulting build. Lake resolves packages, uses matching artifacts, and rebuilds affected modules so Lean can check them. The job log gives the contributor and reviewers a shared record for that revision. [Lake reference](https://lean-lang.org/doc/reference/latest/Build-Tools-and-Distribution/Lake/)

The required build job also checks for two ways a proof change can appear to work while relying on different assumptions.

- It fails if the build reports that a declaration uses `sorry`, Lean’s placeholder for an unfinished proof.
- It checks that the axiom dependencies of all five theorems match `propext`, `Classical.choice`, and `Quot.sound`.

The project also uses Comparator to compare the proved statements with a separate challenge file and check the proof with Lean’s kernel and nanoda. Those checks help reviewers distinguish a change in the proof from a change in the theorem it establishes. The CI-esta benchmark measures the required build job through its axiom check. [Build workflow](https://github.com/leanprover-community/riemann-hypothesis/blob/c5451bd3ba92480e05c4218f5221bb2900c58706/.github/workflows/build.yml) · [Statements and Comparator checks](https://github.com/leanprover-community/riemann-hypothesis#theorem-statements)

## How CI-esta saves the dependency work

CI-esta reads job and step timings from GitHub Actions after a run completes. Those timings tell you where to intervene. A build that spends most of its time downloading dependencies calls for a different change from one that spends most of its time elaborating proofs. In 25 merge-queue jobs of the Riemann build, the three cache-restore steps took a median 110 seconds of a 150-second job, so we built an action that reuses the prepared dependency tree. [Workflow reporting guide](../docs/github-actions-observability.md) · [Merge-queue job timings](assets/lean-preflight/queue.json) · [CI-esta report for a separate Lake tooling probe](https://github.com/aviadr1/riemann-hypothesis/actions/runs/45882949920)

1. A runner operator builds a **read-only seed** from a trusted checkout of the project. In this case it contains the pinned Lean toolchain, the dependency checkouts, and their available compiled artifacts.
2. At checkout, `restore-lean-packages` compares `lean-toolchain`, `lakefile.toml`, and `lake-manifest.json` byte for byte and checks the pinned Git revisions of the seeded packages. A missing seed, mismatched input or unsuccessful restore takes the existing dependency setup path.
3. On a hit, the action copies the packages into the job’s own `.lake/packages`. On a reflink-capable filesystem such as Btrfs, the private copy can share data blocks with the seed until a write. With toolchain linking enabled, Elan can use the preinstalled compiler and Lake gets a writable artifact cache in the workspace by default.
4. The project still checks Tau Ceti’s Mathlib pin and its restrictions on imports in the proof statements. Lake can fetch anything missing from the current dependency graph. The project restores its own build cache, runs `lake build`, and checks the five theorems’ axioms.

For a pull request from a fork, the job can write to its copy of the dependencies. Future jobs get their own copies from the operator’s read-only seed. The action ships in CI-esta 1.34.0. An adoption PR, open and not yet reviewed when this was written, documents how the seed would be provisioned on the project’s runners. [Lean seed setup guide](../docs/lean-packages.md) · [CI-esta 1.34.0](https://github.com/gigaverse-app/ci-esta/releases/tag/v1.34.0) · [Proposed adoption PR](https://github.com/leanprover-community/riemann-hypothesis/pull/8719)

## From 234 seconds to 110 seconds

On November 26, we replayed the same batch proof source on two GitHub-hosted Linux jobs in a fork of the project, with Btrfs workspaces and fresh job homes. Both verified the same `src` Git tree and passed the build and all five axiom checks. The seeded job ran the adoption branch, five commits ahead of the cold job’s commit, so its workflow and cache scripts differ. This pair is a single measurement. An earlier series ran four replays per input in each mode, back to back on one runner per mode. It included a small source PR alongside the batch. [Paired replay](https://github.com/aviadr1/riemann-hypothesis/actions/runs/45881900524) · [Four-replay series](https://github.com/aviadr1/riemann-hypothesis/actions/runs/45878587436)

| Riemann proof workload | Fresh dependency setup | Seeded dependencies | Speedup |
| --- | ---: | ---: | ---: |
| Batch proof, paired replay | 234 s | 110 s | 2.13× |
| Source PR, median of four replays per mode | 272 s | 123.5 s | 2.20× |
| Batch proof, median of four replays per mode | 263 s | 129 s | 2.04× |

Times run from the start of checkout to the end of the axiom check. In the paired replay, the seed restore took 13 seconds and the Mathlib download step could be skipped. Both jobs used the project’s existing build cache and `lake build` took 6 seconds in each. Preparing the seed took 195 seconds once, outside the measured interval, which also excludes queue time. An ext4 trial took about 49 seconds to restore the seed, illustrating why filesystem choice matters. None of these runs used the project’s self-hosted runners. Actual pull-request latency also depends on runner capacity, the seed hit rate, and how much Lean must recompile. This replay compiled almost nothing, and on November 26 the five fork pull-request jobs we saw start had first waited more than nine hours for a runner, which a seed does not shorten. [Queue snapshot](assets/lean-preflight/queue.json) [Cold job steps](https://github.com/aviadr1/riemann-hypothesis/actions/runs/45881900524/job/140123023845) · [Seeded job steps](https://github.com/aviadr1/riemann-hypothesis/actions/runs/45881900524/job/140123023446) · [Ext4 trial](https://github.com/aviadr1/riemann-hypothesis/actions/runs/45880469629)

We also checked what happens when the seed is missing and when a proof is invalid. The first run fetched dependencies through the normal path. In the second, the seed restore succeeded and `lake build` still rejected the invalid proof. A separate replay passed the build and axiom checks and uploaded the cache artifact used by the merge-queue workflow. [Missing-seed run](https://github.com/aviadr1/riemann-hypothesis/actions/runs/45879474875) · [Invalid-proof control](https://github.com/aviadr1/riemann-hypothesis/actions/runs/45880469629) · [Cache staging replay](https://github.com/aviadr1/riemann-hypothesis/actions/runs/45880765174)

## Why the cache verifier can fetch less Git history

Checking out Git history took 59 seconds of an 87-second cache publication job. The verifier reads a commit's source tree, build configuration, and toolchain pin. It gets the build provenance from the GitHub API. A shallow checkout therefore supplies the inputs for a push to main. For a manual run targeting another commit, the proposed workflow fetches that SHA at depth one and runs the verifier from the trusted workflow revision. The pull request was open when this was written. [Production timing](https://github.com/leanprover-community/riemann-hypothesis/actions/runs/45849728902) · [Project pull request](https://github.com/leanprover-community/riemann-hypothesis/pull/8757)

We replayed both cases on fresh GitHub-hosted Ubuntu runners. Each pair is one run per checkout depth and used the same upstream build artifact and Lean toolchain. All four jobs verified the artifact. Times run from job start to completion, including checkout, artifact discovery and download, toolchain installation, and verification. Production storage writes and the downstream acceptance build were outside this replay. [Paired verification jobs](https://github.com/aviadr1/riemann-hypothesis/actions/runs/45886588389)

| Commit to verify | Full history | Shallow checkout | Speedup |
| --- | ---: | ---: | ---: |
| Same as the workflow revision | 83 s | 36 s | 2.31× |
| Earlier than the workflow revision | 80 s | 36 s | 2.22× |

To reproduce the CI-esta report in Bash, name the four matrix jobs as the benchmark's gates. The job list gives the individual durations even though the four runners executed concurrently.

```bash
repo=aviadr1/riemann-hypothesis
run=45886588389
gates=()
while IFS= read -r job; do
  gates+=(--gate "$job")
done < <(gh api "repos/$repo/actions/runs/$run/jobs" --jq '.jobs[].name')
GH_TOKEN="$(gh auth token)" ci-esta report --repository "$repo" --run-id "$run" "${gates[@]}"
```

If checkout dominates a Lean job, inspect its Git commands before choosing a depth. Reading a named tree needs one commit. Searching for the nearest published ancestor needs history. Replaying an older target exercises the difference.

## How much faster can Lake itself get?

When the package artifacts are already on disk, setup and compilation still have costs of their own. Lake computes which transitive imports a module needs and where their artifacts live. Lean’s upstream `inundation` benchmark can exercise this work in isolation by computing module setups against a prebuilt import graph. [Upstream benchmark](https://github.com/leanprover/lean4/pull/16083)

We built two Lake binaries from the Lean 4.37.0-rc1 sources and changed the candidate to track visited imports with hash sets. On a fixture that requested 1,080 module setups, we alternated the order of the two binaries for eight pairs on the same runner. Median wall time fell from **2.38 to 2.15 seconds**, about **10%** on this synthetic fixture, while median peak memory rose about **6%**. That is a tradeoff to check on real Lean projects before proposing a Lake change. The Riemann adoption PR uses the released Lake toolchain and its CI speedup comes from dependency setup. [Lake experiment and all 16 measurements](https://github.com/aviadr1/riemann-hypothesis/actions/runs/45883970283/job/140129973292) · [Experiment workflow](https://github.com/aviadr1/riemann-hypothesis/blob/440920045b4c812ee593c0e6772c7a4aeba8846b/.github/workflows/lake-import-sets.yml)

The same investigation turned up two smaller ways to help upstream. A dry-lint scan of Lake’s Lean sources rated two unrelated multiline strings as identical. That false match led to a merged fix. A selective-deps probe also showed that changing a Lake test fixture could select its reader, while changing a shared shell helper selected both tests in the probe. That gives maintainers a concrete way to try narrower CI for fixture-only edits. [Merged dry-lint fix](https://github.com/gigaverse-app/dry-lint/pull/202) · [Lake fixture dependency probe](https://github.com/aviadr1/riemann-hypothesis/actions/runs/45883619457)

## Make a contribution someone can verify

For the Riemann formalization, pick an open issue and propose a change a reviewer can check. Explain which part of the proof gets easier to understand or maintain, or link the run that shows where CI is spending time. [Riemann Hypothesis issues](https://github.com/leanprover-community/riemann-hypothesis/issues) · [Project guidance](https://github.com/leanprover-community/riemann-hypothesis#riemann-hypothesis)

If you maintain a Lean project, pick a representative proof change and measure its path to a verdict. Record runner wait and setup separately, and keep the full proof checks in both runs. If dependency hydration dominates, try a trusted seed and compare a hit with a fresh job. If module setup or proof elaboration dominates, use a warm workspace to isolate the repeated work and bring that benchmark upstream. Share the revision, toolchain, runner, and run links so the next contributor can repeat the experiment. [Measure your CI critical path](../docs/tutorials/measure-critical-path.md) · [Prehydrate Lean dependencies](../docs/lean-packages.md)

The original release made the proof available for others to check. The cleanup will determine how easily another person can understand a step, change it, and check it again.

See [How Lean contributors can get useful feedback sooner](lean-preflight-case-study.md) for the fork queue measurement and a replay of historical proof failures.

See [Mathematical engineering](mathematical-engineering.md) for what a week of this work taught us, including the pull requests we withdrew.
