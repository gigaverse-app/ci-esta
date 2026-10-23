---
title: CI-esta documentation
description: Measure GitHub Actions critical paths, cache Python environments, and verify CI improvements.
---

# CI-esta

Measure GitHub Actions critical paths, cache Python environments, and verify CI improvements.

[Get started](../docs/quickstart.md){ .md-button .md-button--primary }
[Source on GitHub](https://github.com/gigaverse-app/ci-esta){ .md-button }

## Follow a measured example

[Measure the actual critical path](../docs/tutorials/measure-critical-path.md). Apply the steps to your own
repository, and inspect the original runs, retained checks, and measurement limits.

## Measure first, then optimize the work that matters

Use CI-esta to explain where GitHub Actions time goes. Start with a report of a
completed run. Then choose caching, selection, evidence reuse, or parallelism
based on the measured bottleneck and the checks your workflow must preserve.

- [Add a completed-run report](../docs/quickstart.md#report-a-completed-workflow): collect job and step timings without adding work to the validation gate.
- [Read the critical path](../docs/critical-path.md): distinguish execution time from waiting and inspect the Gantt chart.
- [Cache a Python environment](../docs/environment-cache.md): retain locked synchronization and repair invalid restores.
- [Reuse completed evidence](../docs/evidence-reuse.md): skip equivalent work only when its complete inputs and successful result match.
- [Preserve required gates](../docs/selected-gates.md): reject missing or incomplete validation.
- [Compare measured outcomes](../docs/measured-impact.md): inspect the original runs and attribution limits.

## Use the tools together

[Choose the tool for your problem](ecosystem.md). Each project works on its own;
combine them when you need both faster feedback and evidence that the required
work still happened.

## Versions and support

`latest` follows the main branch. Release-specific documentation is available
through Read the Docs when that release contains the site configuration.
Use [GitHub issues](https://github.com/gigaverse-app/ci-esta/issues) for a minimal
reproducer or a missing explanation. [Contributions](../CONTRIBUTING.md) are welcome.
