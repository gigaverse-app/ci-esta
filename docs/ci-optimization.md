# Make CI faster without weakening its result

Start with one completed workflow and the checks required to merge. Add the
[completed-run observer](github-actions-observability.md), retain its JSON, and
record the source run ID, attempt, head SHA and exact gate names. Fix one measured
cost at a time. The [adoption audit](adoption-audit.md) distinguishes shipped
capabilities from integrations still missing in the example repositories.

## Read the timeline before changing parallelism

The report's job Gantt shows when jobs actually ran. The step table identifies
whether the time went to checkout, dependencies, services or tests. Runner time
is summed work; elapsed time includes waiting and overlap.

For example, two independent 60-second jobs can finish in roughly 60 seconds
while consuming 120 runner-seconds. Adding `needs: first` to the second can make
the same work take 120 seconds. Conversely, making an off-path 20-second job ten
seconds faster might not shorten a 60-second merge path at all. These are
illustrations, not measurements from a CI-esta benchmark.

Enable [critical-path analysis](critical-path.md) to read the source workflow's
`needs`, compute execution slack and separate execution from observed delays.
Read matrix limits, environments and service startup alongside the observed timeline.
Use explicit aggregate gates to define readiness. Never drop a prerequisite
just because it appears slow; remove an edge only when the jobs do not exchange
required outputs or evidence.

## Cache the right thing

| Cache | What it saves | Required boundary |
| --- | --- | --- |
| uv download cache | Repeated downloads/builds | Lock/manifests and platform; still sync the environment |
| Complete `.venv` | Environment installation | OS/architecture, exact interpreter, all manifests/locks, groups/extras, workspace layout and install mode |
| pytest-selective graph | Repeated dependency analysis | Use the action's cache and internal validation; uncertain state rebuilds |
| Test durations | Better shard balance | Keep a seed/fallback; stale estimates may affect balance, never test membership |
| Database/schema dump | Repeated migrations | Database/tool version and every schema/seed input; product-specific |
| Image layers or immutable images | Repeated builds/pulls | Complete build identity and prior verification; caller owns policy |

Begin with the package manager cache:

```yaml
- uses: astral-sh/setup-uv@20cfd1bf945f4377ade1205e4dbc17946fc9a30d # v10.0.1
  with:
    enable-cache: true
    cache-dependency-glob: |
      **/uv.lock
      **/pyproject.toml
- run: uv sync --locked
```

This is not a `.venv` cache. Use the new [setup-cached-uv action](environment-cache.md)
to restore and validate a complete environment. The inherited `setup-python-uv`
retains its original simpler contract. If measured installation cost justifies one,
validate the restored interpreter, sync after partial matches, and rebuild on
unusable caches. Skip synchronization only under a reviewed complete exact-key
contract. Editable installs and workspace paths need special care. Save shared
environments from trusted default-branch runs; use caller-owned authentication
without storing credentials in artifacts or cache payloads. Compare cold and
warm runs separately before publishing savings.

## Select work at the useful level

Use [pytest-selective lane planning](https://github.com/gigaverse-app/pytest-selective/blob/main/docs/ci.md#select-whole-ci-lanes)
when jobs start different services or must produce complete conformance evidence.
Use file selection inside a large ordinary pytest suite. Declare data reads,
subprocess entry points, external pins and workflow inputs that imports cannot
discover. Keep routing regression tests, metadata/build checks and full checkpoints.

Test a README change, an ordinary source change, a shared helper change, an
external input change and missing history using real Git commits. Check both
the selection and the jobs that actually execute. A failed planner must not
silently skip validation; invalid declarations need repair. Never call pytest
with an accidentally empty argument list.

## Close the timing feedback loop

Start with `pytest --durations=20` and existing xdist support. Add balanced pools
only when test execution dominates enough to justify their startup and artifact
cost. CI-esta delegates the partitioning algorithm to pytest-selective.

```bash
# This CLI requires a manifest. An empty seed uses fallback estimates for unknown files.
test -f .test_durations || printf '{}\n' > .test_durations
ci-esta-pytest plan --test-root tests --shards 4 --exact-files \
  --durations .test_durations --output-dir splits
```

The plan is not execution. Integrate the generated exact-file plan with your
runner through [plan-pytest-shards](../actions/plan-pytest-shards/action.yml)
and [completion verification](../actions/verify-pytest-completion/action.yml).
For local concurrent pools, inspect `ci-esta-pytest run-local --help`; its worker
command must consume the selected shard and produce the expected completion
evidence. Do not replace a conformance suite's own report validators.

Upload per-shard JUnit and duration manifests, download them into one directory,
then use [pytest-timings](../actions/pytest-timings/action.yml) with the
exact expected shard count. Cache the merged duration output after a complete
trusted run. Partial or missing artifacts are not a successful full reference.
Require every distributed pool and a complete, disjoint partition before issuing
an aggregate receipt. Compare 2/4/8 workers on the same workload; more workers can
increase contention and total runner time.

## Report the selection and reuse only proven work

The [observer example](github-actions-observability.md) consumes lane artifacts
by default. A caller using file selection can add:

```yaml
# Under jobs.report.with in the reusable observer example:
post-sticky: true
test-selection-artifact: test-impact-explanation
full-suite-reference-artifact: ci-full-suite-reference-v1
```

The current file-section reader requires `post-sticky: true`; grant comment
permission only if posting a PR comment. Producers must actually upload those
artifacts. Missing full-suite references leave savings unmeasured. A report's
gate elapsed time is unassessed without exact required-gate selectors.

After selection works, consider [evidence reuse](evidence-reuse.md). Start with
whole-tree identity; narrow inputs only after proving the full dependency
contract. Put the completion receipt after tests and every required validator.
Exercise a successful reuse, changed input, missing proof, failed prior run and
manual rerun. Retain full runs to catch changing external dependencies.

## Demonstrate the improvement

Keep paired source/checkout identity and attempt numbers. Compare selected/full
work at the same head, and compare cold/warm caches separately. Record elapsed
seconds, runner-seconds, executed jobs/tests, preserved gates and observer cost.
Include slow setup and reruns rather than trimming inconvenient observations.
Use several pairs before claiming a stable average; one pair is an example.
The [published measurement](benchmarks/2026-10-22.md) illustrates the evidence
format. These tools do not turn estimates into a billing invoice.

For an agent-driven adoption, use the [portable skill](../skills/ci-esta/SKILL.md)
and [pytest-selective's skill](https://github.com/gigaverse-app/pytest-selective/tree/main/skills/pytest-selective).
Require the agent to report extracted, configured and live-verified states
separately, with remaining gaps instead of a blanket completion claim.
