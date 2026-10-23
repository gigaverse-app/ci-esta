# Learn from tests that already run

Keep the JUnit report from a successful test lane, then use its file costs to
balance the next run. Timing data only affects placement. It never proves that
a test passed on the current commit and never authorizes omitting a file.

```bash
uv run pytest -q -n 4 --junitxml=junit.xml
ci-esta-pytest learn junit.xml --output .test_durations
ci-esta-pytest plan --durations .test_durations --test-root tests \
  --shards 4 --exact-files --output-dir splits
```

`learn` supports pytest's default xunit2 classname format and xunit1 file paths.
It sums testcase durations per current file. Missing, malformed, failed and
non-finite reports fail before replacing an existing manifest. Unknown paths
are counted and excluded. Skipped cases do not teach a zero cost. The planner
still inventories current files and assigns an explicit fallback to unknown
files. New tests therefore remain in the plan. Use separate manifests for
Python versions, operating systems, services and dependency variants.

For CI, add `learn-test-timings` at a reviewed immutable CI-esta
commit after a successful pytest step. Supply `junit-pattern: junit.xml` and a
unique `artifact-name`, such as `test-timings-py311-linux`. It requires uv, writes
`.ci-test-durations.json`, and retains both that file and the source XML for 21
days. Its output is an advisory artifact, not a completion receipt. Download the
appropriate successful default-branch artifact before planning a later run;
on a miss, initialize `{}` and let inventory fallback cover every file.
Do not combine reports for overlapping matrix variants: that sums repeated work.
For a partial selected run, the learned costs cover only the observed files.

## Retain history across partial runs

Enable retention when affected-test selection runs only some files. It keeps
the last observation for untouched files, replaces observed files only with a
newer observation, and gives removed files the existing 14-day grace period.
No retention is enabled merely by upgrading CI-esta.

### GitHub Actions: opt in with one environment key

Use the same `history-key` before planning and after successful tests. Choose a
different key for each OS, Python version, service and fixed marker lane. These
actions install their own tool environment; your application needs no new dependency.
Pin a reviewed CI-esta commit containing these actions until this feature is
released on `v1`.

```yaml
permissions:
  contents: read
  actions: read
steps:
  - uses: actions/checkout@v7
  - uses: gigaverse-app/ci-esta/actions/restore-test-timings@v1
    with:
      history-key: unit-linux-py314
  # Plan using .test_durations, then run every selected file completely.
  - run: uv run pytest tests --junitxml=junit.xml
  - uses: gigaverse-app/ci-esta/actions/learn-test-timings@v1
    with:
      junit-pattern: junit.xml
      artifact-name: unit-timings
      output: .test_durations
      history-key: unit-linux-py314
      complete-files: 'true'
```

`complete-files` declares that the reports include every case belonging to each
observed file **within this fixed lane**. Whole-file affected-test selection is
supported. Ad hoc `-k`, changing marker filters, node-level subsets, fail-fast
reports and missing shards cannot satisfy this contract. Validate completion
before learning; JUnit cannot establish which cases were omitted. Aggregate
all disjoint shard reports into one publisher per history key per run.

For separate planning and matrix jobs, restore once in the planner and pass that
exact duration file to every worker as an artifact. Independently restoring the
latest history in each worker can yield different shard assignments while
another run publishes an update. The
[sharding workflow](../examples/pytest-shards/workflow.yml) shows the producer side;
gigaverse-ai also freezes the planner's input for all pools.

Publication is limited to push, schedule and manual runs on the trusted branch,
which defaults to the repository's default branch. Readers require the producing
run to have completed successfully. PRs can read and compute costs but cannot
publish shared history, including same-repository PRs. Keep the learning action
after test/completion checks; `continue-on-error: true` is appropriate when
history publication should not block validation.

| Override | Default | Use |
| --- | --- | --- |
| `history-key` | Empty on learning | Explicit opt-in; change the key for a fresh history |
| `history-publish` | `true` | Set `false` for a read/compute-only rollout |
| `history-branch` | Repository default branch | Isolate a trusted branch experiment |
| `history-max-downloads` | `20` | Raise for many concurrent uncovered writers |
| `history-retention-days` | `90` | Artifact lifetime, within repository limits |
| Restore `strict` | `false` | Fail instead of falling back when diagnosing history access |

Remove the history key and restore step to opt out. Existing artifacts remain
available until GitHub expires them. A missing or unavailable history keeps a
committed seed, or writes `{}` so inventory fallback still plans every file.
Seed values for files never observed in history remain usable. No timing history
can authorize omitting a test or satisfy a completion gate.

### Concurrent publication

Each run publishes its own checkpoint artifact. A subsequent reader reconciles
every uncovered checkpoint by source observation time, not finish/download time.
If A and B start from the same history and observe different files, both updates
survive even if they finish in reverse order. A new checkpoint records the artifact
IDs it incorporated, so later readers skip those ancestors. Normally one checkpoint
download is sufficient. The 20-download budget fails visibly rather than publishing
truncated history; restore falls back unless strict mode is enabled.

Reruns replace only their own run's checkpoint, with producer attempt validation.
No workflow-wide concurrency lock is required. This avoids GitHub concurrency
queues dropping pending publishers. If all checkpoints expire after a long idle
period, the seed/unknown-cost fallback applies and history starts accumulating again.

### CLI and runnable tutorial

Install `ci-esta[pytest]`, or use the repository's `uv sync --locked` environment:

```bash
ci-esta-pytest learn junit.xml --history .ci/timing-history.json \
  --history-key unit-linux-py314 --complete-files --output .test_durations
```

The CLI inventories tracked Python files with Git, independently of selected
files. For a non-Git checkout, pass `--tracked-files inventory.txt` containing the
complete checkout's paths, one per line. Use `--working-directory` when report
paths are relative to another directory. For delayed ingestion, pass the source
run's timezone-aware `--observed-at`, never the download time. The default is now
for immediate local ingestion. Keep each key in its own history file.

Local updates lock the history file across read/merge/write and atomically replace
both outputs. An interrupted output write can be recovered without rerunning tests:

```bash
ci-esta-pytest history .ci/timing-history.json --history-key unit-linux-py314 \
  --output .test_durations
uv run python examples/timing-history/run.py
```

The executable tutorial runs real pytest reports in a temporary Git checkout,
learns two partial runs, replays a stale report, and verifies the complete shard
inventory. It also runs in CI. To exercise real GitHub artifacts, dispatch the
CI workflow with `timing-example: alpha` and `timing-example: beta` independently,
using the same fresh `timing-history-key`. After **both workflows succeed**,
dispatch `timing-example: verify`. The
[example workflow](../.github/workflows/timing-history-example.yml) checks that both
updates survived. Its explicit branch override keeps experiments separate from
production history.

### Low-level Python API

`ci_esta.testing.timing_history` provides the backend's existing incremental
history contract for consumers that maintain a persistent timing cache:

```python
from dataclasses import asdict
from datetime import datetime, timezone

from ci_esta.testing.timing_history import load_observations, merge_observations

observations, removed = load_observations(state, tracked_files, datetime.now(timezone.utc))
merge_observations(observations, validated_complete_file_durations, observation_stamp)
state.update(
    observations={node: asdict(value) for node, value in observations.items()},
    removed_files=removed,
)
durations = {node: value.seconds for node, value in observations.items()}
```

Keep one history per execution environment. The caller validates input durations,
supplies the complete current tracked-file inventory, and persists the returned
state alongside its own processed-run metadata. Stamps must sort in observation
order; the backend uses a run-start timestamp followed by zero-padded run ID and
attempt. An older or equal stamp cannot replace a newer file observation or
resurrect removed test nodes. A newer observation replaces all nodes in that
complete file while preserving files absent from the update. Empty updates do
nothing. Partial observations *within* a file are not supported.

Removed files remain available to older PRs for 14 days from the first observed
removal, including the exact boundary. Later loads preserve that removal date;
restoring a tracked file clears it. Existing `observations` and `removed_files`
JSON caches need no migration. The library neither fetches artifacts nor writes
cache files. `learn` retains its existing report-to-manifest replacement behavior;
retained history is explicit and never authorizes skipping tests.

## Execute an exact file plan

The files in `splits/group-N.txt` contain one test path per line. Pass them as
individual arguments, not shell text. Never invoke bare pytest for an empty
shard: that would rerun the entire suite. This small runner is sufficient for
independent tests without application services:

```python
import os
import subprocess
import sys
from pathlib import Path

index = int(os.environ["GV_PYTEST_SHARD_INDEX"])
paths = Path(f"splits/group-{index}.txt").read_text().splitlines()
if paths:
    raise SystemExit(subprocess.run([
        sys.executable, "-m", "pytest", "-q", *paths,
        f"--junitxml=junit-{index}.xml",
    ]).returncode)
```

Save it as `run_shard.py`, then run:

```bash
ci-esta-pytest run-local --shards 4 --log-dir shard-logs -- python run_shard.py
ci-esta-pytest learn junit-1.xml junit-2.xml junit-3.xml junit-4.xml \
  --output .test_durations
```

Only list nonempty planned shards when learning; retain an explicit expected
shard inventory for completion checks. Production services require per-shard
database, queue, port and temporary-directory isolation. See
[runner pools and diagnostics](runners-and-diagnostics.md). Preserve domain
conformance and coverage gates when changing scheduling.

## Decide whether sharding is actually useful

On October 23, a local run of CI-esta's 1,050 tests learned 62 file costs with
zero unmapped cases. Four planned groups predicted 9.4 seconds each and all
1,050 tests passed in the four serial processes (145, 215, 190 and 500 tests).
Measured shard pytest durations were 10.15, 10.13, 10.18 and 10.09 seconds. This
checks the learning-to-execution loop; it is one local sample, not a hosted CI
speedup claim. CI-esta keeps its existing four xdist workers because these short
suites do not justify extra hosted runners. Due and obligation retain their
service isolation and conformance lanes; their timing artifacts expose where
balancing might help without changing correctness contracts.

Compare repeated runs of the same checkout, dependencies, runner and full test
inventory. Measure workflow-to-gate time and summed runner seconds, not just
pytest time. Use [critical-path analysis](critical-path.md) to distinguish an
unbalanced test lane from dependency setup or scheduling delay.
