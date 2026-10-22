# Diagnose slow Python CI without cutting checks

Start with the slow step. A workflow that takes five minutes can contain a slow
test, a slow package install, or jobs waiting on each other. Each needs a different
fix. CI-esta's [completed-run report](github-actions-observability.md) keeps the
measurement outside the validation workflow and separates admission delay from
runner time. Use pytest's `--durations=20` to see setup, call and teardown costs.

## Check the measurement runtime itself

pytest-selective's [Windows 3.11 run](https://github.com/gigaverse-app/pytest-selective/actions/runs/39848431314)
spent 238 seconds in pytest while coverage warned that `coverage.tracer` was
missing. The lockfile's artifact list lacked the compiled Python 3.11 wheel. The
wheel was available by the time we investigated; refreshing metadata repaired
the install while retaining coverage 7.17.0 and the entire test matrix.

```bash
uv run --locked python -m coverage --version
# If a compiled wheel is missing from the lock, check available artifacts first.
uv lock --refresh-package coverage
uv sync --locked --reinstall-package coverage
uv run --locked python -m coverage --version
```

Review the lock diff. Do not make CI refresh dependencies on every run or disable
coverage to hide the cost. [The recorded repair](https://github.com/gigaverse-app/pytest-selective/pull/11)
reproduces the missing tracer before the refresh and loads the compiled tracer
afterward. Timing still varies with runners and caches, so compare completed
same-workload runs before claiming a percentage improvement.

## Select work, then reuse proof

pytest-selective owns dependency analysis, lane planning and guards against
unexplained global conftest expansion. CI-esta owns evidence that an admitted
lane actually passed. These answer different questions. A small selection does
not prove a passing run, and an unchanged Git tree does not capture every change
in an external database or service.

Keep full-suite overrides, required gates and conformance report validators.
Reuse [lane evidence](evidence-reuse.md) only with complete declared inputs and a
positive completion receipt. Cancel stale revisions without letting an old
manual rerun cancel newer work. Observe the real workflow after changing either
admission policy or cancellation.

For measured examples, see pytest-selective's
[paired Due and pytest-obligation runs](https://github.com/gigaverse-app/pytest-selective/blob/main/docs/benchmarks/2026-10-22.md).
Those examples include successful full controls and runner-time measurements;
they are not a promise that every repository will achieve the same savings.
