# CI-esta: make GitHub Actions faster, with evidence

See what holds up your PR, avoid repeating validated work, and run the remaining
tests efficiently. CI-esta adds reports, environment caching, reusable execution
evidence and test scheduling to your existing GitHub Actions workflows. No account,
hosted service or application-language change is required.

[![CI](https://github.com/gigaverse-app/ci-esta/actions/workflows/ci.yml/badge.svg)](https://github.com/gigaverse-app/ci-esta/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/ci-esta)](https://pypi.org/project/ci-esta/)
[![Apache-2.0](https://img.shields.io/badge/license-Apache--2.0-blue)](LICENSE)

## Choose your first improvement

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
- uses: gigaverse-app/ci-esta/actions/setup-cached-uv@main
  with:
    python-version: '3.12'
    sync-args: '--group test'
- run: uv run --no-sync pytest
```

Use your project's interpreter and dependency groups. The root action,
`gigaverse-app/ci-esta@main`, produces the report; individual actions share the
`actions/` directory, such as `/actions/setup-cached-uv` and `/actions/plan-runner-pools`.

The shared `actions/NAME` paths are new on `main`. Use a reviewed commit that
contains them, or `@main` while evaluating. Once a 1.x release includes these
paths, `@v1` will receive compatible minor and patch upgrades automatically.
The root default remains available; named actions live only under `actions/`. [Action API and versioning](docs/actions.md).

[Copy the complete reporting or cache workflow](docs/quickstart.md). The actions
set up their own tools; using them does not require adding CI-esta to your app.
For Python execution commands and plugins, install `ci-esta[pytest]` in the test
environment. Reporting and evidence actions also work with non-Python projects;
[Bun users have a native selection adapter](docs/bun-test-selection.md).

## Give your agent a concrete task

```text
Read https://raw.githubusercontent.com/gigaverse-app/ci-esta/main/skills/ci-esta/SKILL.md
Measure a completed CI run and improve its largest avoidable cost. Use the public
action entry points and tested quickstart examples. Compare one large runner with
multiple runners if tests dominate. Keep required checks and full-suite coverage,
and show the workflow changes, test inventory, elapsed time and runner usage.
```

[Install or update the portable skill](docs/agents.md). The skill, README and
[quickstart](docs/quickstart.md) use the same recipes. Updating the Python package
does not update an installed agent skill.

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
project. [Evidence reuse](docs/evidence-reuse.md) and [strict gates](docs/validation.md)
explain these boundaries. The [optimization guide](docs/ci-optimization.md) connects
selection, timing feedback, execution and measurement in order.

## Further documentation

- [Public actions](docs/actions.md) and [full toolkit catalog](actions/README.md)
- [Critical path and slack](docs/critical-path.md), [cost reporting](docs/github-actions-observability.md), and [environment caching](docs/environment-cache.md)
- [Learned timings](docs/learned-test-timings.md), [runner pools](docs/runners-and-diagnostics.md), and [Python CI tuning](docs/python-ci-tuning.md)
- [Integrations](docs/integrations.md), [alternatives](docs/alternatives.md), and [revision-bound adoption audit](docs/adoption-audit.md)
- [Contributing](CONTRIBUTING.md), [releases](RELEASING.md), and [source provenance](PROVENANCE.md)

Install the standalone CLI with `pip install ci-esta`.
Base reporting needs Python 3.11+ and neither pytest nor pytest-selective.
Use `ci-esta[selection]` for Python selection reports or `ci-esta[pytest]` for
pytest execution tools. Before 1.0, review each minor release's migration notes.
