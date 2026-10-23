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
