---
title: "Mathematical engineering: what a 300,000-line proof needs after it is true"
description: Lean's kernel accepted the Riemann Hypothesis proof. Making it readable is maintenance work on a large codebase. One week of measurements, tools, withdrawn pull requests and bugs in our own tools.
---

# Mathematical engineering: what a 300,000-line proof needs after it is true

Lean's kernel has accepted a proof of the Riemann Hypothesis. That settles whether the theorem holds. It does not make the proof something a person can read, teach or change. The community edition is about 300,000 lines of Lean in 801 files, and its maintainers ask for one thing: a proof that people can read. [Repository and goals](https://github.com/leanprover-community/riemann-hypothesis#riemann-hypothesis) · [Contribution rules](https://github.com/leanprover-community/riemann-hypothesis/blob/main/AGENTS.md)

Work on a text of that size is engineering. The questions are the ones a large codebase raises. How long until I know my change is correct? Where is the same argument written twice? Which change is an improvement, and who decides? We call the practice *mathematical engineering*. Mathlib, Flyspeck and the Liquid Tensor Experiment practised it for years. What is new is a proof of this size and consequence arriving at once, written with a machine, and handed to a crowd to maintain.

We spent a week applying three software-maintenance tools to it: [CI-esta](https://github.com/gigaverse-app/ci-esta) for CI timing, [dry-lint](https://github.com/gigaverse-app/dry-lint) for repeated code, and [pytest-selective](https://github.com/gigaverse-app/pytest-selective) for test selection. This is what we measured, including what went wrong.

## The kernel tests truth and nothing else

In software, a passing test suite leaves room for doubt. In Lean, a passing build with the axiom check leaves almost none: the five theorems follow from three standard axioms. A refactoring that compiles cannot make the theorem false.

That safety is why refactoring a proof is attractive, and why it is easy to do badly. The kernel accepts a proof that is shorter and harder to read. The project's rules say so directly: "A change that makes the code shorter or faster but harder to read is not welcome." Readability has no checker. A person reviews it.

## Measure the wait first

On November 26 the project had **1,728 queued pull-request builds**. Five fork jobs that had started had waited **9.3 to 10.3 hours** for a runner. In the merge queue the runner wait was a median of 1 second, and restoring caches took a median **110 seconds of a 150-second job**. [Queue snapshot](assets/lean-preflight/queue.json) · [Method](lean-preflight-case-study.md)

Those two numbers call for different work. A prepared dependency seed shortens the 110 seconds: in one paired replay on GitHub-hosted runners in a fork, the job took 110 seconds with the seed and 234 without. The project has not adopted it, and we have not measured it on the project's runners. [Replay and limits](riemann-lean-ci.md)

No cache shortens a ten-hour queue. A contributor who can check a fix locally does not need the queue for the first answer. From a failed build log, `ci-esta-lean retry` prints the `lake build` command for the modules that failed. In one local run, the targeted build reproduced a historical failure in 16 seconds with caches restored. [Case study](lean-preflight-case-study.md)

## A duplicate is a question for a mathematician

Dry-lint ranks pairs of declarations and proof fragments that look alike. On this proof it produced the candidates behind 20 refactoring pull requests in two days. As of November 27, **18 are open, none is merged, and we withdrew 2**. The open ones remove 584 lines and add 324. An AI review agent run by the project has rated most of them ready; a maintainer still has to approve each one. [The pull requests](https://github.com/leanprover-community/riemann-hypothesis/pulls?q=is%3Apr+author%3Aaviadr1+refactor)

The good ones share a shape: two definitions that passed the same data to the same construction, where one becomes an instance of the other, or one calculation proved twice inside a single theorem and now stated once. [Triangle lifts](https://github.com/leanprover-community/riemann-hypothesis/pull/8837) · [Radical coordinates](https://github.com/leanprover-community/riemann-hypothesis/pull/8856)

The withdrawn ones teach more.

- **The shared proof was longer.** Two counting lemmas had the same three-line proof by induction. We derived one from the other by reindexing the sum. The reviewer answered: "The new proof is longer and harder to follow than the one it replaces." Three lines had become eight. The duplication was real, and removing it made the text worse. [Withdrawn pull request](https://github.com/leanprover-community/riemann-hypothesis/pull/8836)
- **The explanations went missing.** Several refactorings merged two cases and dropped the comment that listed the cases, or replaced `` `z = X_s` with `s ≠ i` `` by a vaguer phrase. Reviewers asked for the comments back each time. A reader needs the case list more than the saved lines. [Example review](https://github.com/leanprover-community/riemann-hypothesis/pull/8908)

A similarity score is the start of a question. Is this the same mathematics, or two arguments that happen to be spelled alike? Would one statement of it read better than two? Only someone who understands the step can answer.

There is also a rule about volume. The project asks contributors who want to make one kind of change in many places to open one pull request and wait for a maintainer's answer before opening the rest. We opened twenty. A tool that produces candidates quickly makes that rule matter more, and we should have followed it.

## Measure the tool before trusting its silence

A scan that reports nothing is only reassuring if it looked everywhere. We compared dry-lint's Lean extractor with the declaration locations the compiler records. The first version found **8,690 of 21,842 declarations, 39.8%**. Six in ten declarations were invisible to it, so "no duplicates found" meant little. After a parser change the figure is **16,875 of 21,971, 77%**. [Coverage audit](https://github.com/gigaverse-app/dry-lint/pull/208) · [Parser change](https://github.com/gigaverse-app/dry-lint/pull/214)

We then reviewed our own week of tool changes the way we would review someone else's, and found defects in each tool.

- `ci-esta-lean retry` printed `lake build +src.Lib.DiscreteSeries.Haar.CayleyChart` on the Riemann repository unless given a flag. No such module exists; the module is `Lib.DiscreteSeries.Haar.CayleyChart`. It also missed failures that carry no line number, such as a bad import or a compiler killed for memory. [Fix](https://github.com/gigaverse-app/ci-esta/pull/309)
- `ci-esta-lean preflight` could report that nothing needed building when a previous failure was misspelled or the tree had uncommitted edits. [Fix](https://github.com/gigaverse-app/ci-esta/pull/310)
- The dependency-seed action failed the job on a runner with Python 3.10, where the documentation promised a fallback. [Fix](https://github.com/gigaverse-app/ci-esta/pull/311)
- The pytest-selective read audit missed files that git read when a command used `-c`, `--work-tree`, a top-rooted pathspec or `git show HEAD:path`. A missed read is the unsafe direction for a tool that decides which tests to skip. [Fix](https://github.com/gigaverse-app/pytest-selective/pull/179)
- Our first article's title said CI was two times faster. The numbers were right. The claim was one replay in a fork, for a change the project had not adopted. [Correction](https://github.com/gigaverse-app/ci-esta/pull/313)

## What we would tell the next project

1. **Keep the full gate.** Every speedup here leaves the build, the `sorry` scan and the axiom checks in place. Faster feedback comes before the gate.
2. **Measure before building.** Queue time, cache time and compile time need different fixes. The step timings say which one you have.
3. **Audit the tool against the compiler.** Lean records where every declaration is. Use that to learn what a source-level tool cannot see.
4. **Treat every finding as a candidate.** Withdraw the change when a reviewer says the old text read better.
5. **Respect the reviewers' queue.** Send one change of a kind and wait for the answer.
6. **Publish the failures.** The withdrawn pull requests and the wrong `retry` command are the most useful results in this article.

Selecting which Lean modules to rebuild is Lake's job, and it does it from the import graph. We looked for a role for test selection inside the Lean build and found none. It helps with the project's Python automation tests, where the selection matched a full run on every mutation we tried. [Selection in the project's CI](https://github.com/leanprover-community/riemann-hypothesis/pull/8672)

## Try it on a Lean project

```sh
# Which workflow runs the proof build, and what to measure next
ci-esta inspect

# From a failed Lake log, the command that rebuilds what failed
ci-esta-lean retry lake.log

# Repeated declarations and proof fragments, for a person to judge
uvx --from 'dry-lint[lean]>=1.16,<2' dry-lint lean-proof-blocks --lines 5
```

The proof is true. Whether people can read it depends on work of this kind, done carefully, and on reviewers with the time to say no.
