---
title: Find the GitHub Actions job actually delaying your PR
description: Measure a workflow's dependency critical path, read its Gantt chart, and verify an optimization against real runs and retained test inventories.
---

# Find the GitHub Actions job actually delaying your PR

Start with the required gate and follow its dependencies. The longest individual
step does not necessarily determine when a PR is ready: another branch may start
late, and several jobs may execute in sequence. Measure both execution and waiting
before changing caching or parallelism.

## 1. Collect one completed run

Install the reporter in an isolated tool environment:

```bash
uv tool install 'ci-esta>=1.1.0,<2'
```

Provide a GitHub read token through `GH_TOKEN` or `GITHUB_TOKEN` using your normal
credential mechanism. Do not put the token in a command argument or commit it.
Replace the repository, run, attempt, and gate with your actual values:

```bash
ci-esta report --repository owner/project --run-id 123456 --run-attempt 1 \
  --gate 'Validation gate' --critical-path --output-dir report
```

For continuous reporting, copy the complete
[completed-workflow observer](../quickstart.md#report-a-completed-workflow) into
the default branch. It needs no application checkout. Keep it independent of the
validation gate, and retain its Markdown and JSON as artifacts.

Check the report's source SHA, attempt, configured gate, collection errors, and
analysis completeness. Missing workflow sources or ambiguous dependencies make
critical-path analysis unavailable. Repair the evidence; do not infer dependency
edges solely from overlapping timestamps.

## 2. Read the two critical paths

| Measurement | Question it answers |
| --- | --- |
| Gate elapsed | How long did this attempt take to reach the required result? |
| Observed dependency chain | Which prerequisites and admission delays kept this gate waiting? |
| Execution-only critical path | Which dependency chain is longest when weighted by measured execution? |
| Slack | How much could a parallel branch change without extending that execution path? |
| Runner-seconds | How much total runner execution did all included jobs consume? |

The Gantt chart highlights the observed chain. Gaps can include runner admission,
scheduling, approvals and resource contention; timestamps alone do not identify
which cause applies. A later rerun starts at that attempt's start, excluding the
human wait before clicking rerun. [Definitions and reusable workflow handling](../critical-path.md).

## 3. Turn the report into one experiment

Open `report/ci-observability.md`. Find the required gate and its observed chain,
then look up the expensive job's steps. Use the JSON alongside the rendered
report when you need exact durations; missing values are unavailable, not zero.

Write down one hypothesis before changing the workflow:

| You observe | Change to try | Keep fixed |
| --- | --- | --- |
| Dependency installation dominates the chain | Restore a validated environment | Lockfile, Python and dependency groups |
| Tests dominate one worker | Balance or parallelize independent tests | Test identities, outcomes and validators |
| A short job starts late | Inspect runner capacity, approval and `needs` | Required dependencies and runner policy |
| A README edit starts test services | Select complete affected lanes | Docs, package checks and full checkpoints |

Run a baseline and candidate with the same workload. Record both run IDs and
attempts, source revisions, cache state, required gate, elapsed time and summed
runner-seconds. Check that all expected tests and post-test validators ran.
Repeat the pair before claiming an average improvement.

## 4. Check an example of the decision

In the [Windows case study](../benchmarks/2026-10-23-windows-saleor.md), the
required gate took 249 seconds in a fresh unchanged control and 185 seconds after
filesystem changes. The execution critical path fell from 242 to 177 seconds.
The full study keeps the source runs, the slower earlier control, test inventories,
and limits on attribution. It does not establish a universal 26% speedup.

The same study's Saleor comparison keeps database preparation warm in both arms;
comparing its cold baseline against a warm candidate would overstate the benefit.
Use that evidence format for your own experiment rather than copying its worker
count or assuming the same bottleneck.

## 5. Choose your next action

- **Unrelated tests run:** follow the [safe lane-selection tutorial](https://pytest-selective.readthedocs.io/en/latest/docs/tutorials/skip-unrelated-ci/).
- **Dependency setup dominates:** use [validated environment caching](../quickstart.md#cache-your-python-environment), compare cold and warm runs, and disable expanded-environment caching if restore costs more than installation.
- **One shard dominates:** inspect [learned test timings](../learned-test-timings.md) and rebalance without splitting required shared state.
- **Repeated equivalent work dominates:** consider [completion evidence reuse](../evidence-reuse.md) only after defining complete inputs and failure invalidation.
- **A serial prerequisite dominates:** evaluate independent jobs, retaining completion checks for every branch.

Report gate elapsed and runner-seconds separately. Parallelism can shorten a gate
without reducing runner usage. Queue variation can make a faster execution path
finish later in one observation. Preserve those results rather than hiding them.
