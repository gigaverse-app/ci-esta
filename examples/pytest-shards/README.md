# Balance tests inside or across runners

This complete recipe plans the current file inventory once, runs each file in
one shard, checks every shard's completion, and learns the next plan's timings.
It is for ordinary independent pytest files in `tests/` in a uv project.

1. Run `uv add --dev 'ci-esta[pytest]'` and commit the lockfile.
2. Copy [workflow.yml](workflow.yml) to `.github/workflows/tests.yml` and
   [run_shard.py](run_shard.py) to `.github/scripts/run_shard.py` in your project.
3. Use your Python version, dependency groups, test roots and default branch.
   Review [public action availability](../../docs/actions.md) and pin a revision
   containing the new entry points before adopting the recipe.
4. Make `Test gate` required. Keep your existing coverage and domain validators;
   place them before that gate succeeds. Combine per-shard coverage before applying
   a whole-suite threshold. This generic example does not replace those checks.

| Layout | `SHARDS` | `SHARDS_PER_RUNNER` | Test-job `runs-on` |
| --- | ---: | ---: | --- |
| One standard runner (example default) | 4 | 4 | `ubuntu-latest` |
| Two standard runners | 4 | 2 | `ubuntu-latest` |
| One provisioned larger runner | 16 | 16 | Your organization's runner label |
| Two provisioned larger runners | 32 | 16 | Your organization's runner label |

If there are fewer files than requested shards, the plan uses only nonempty
groups. New or unmeasured files get fallback costs and remain in the inventory.
The same plan artifact is downloaded by every pool. Timing cache misses merely
affect balance; they do not remove tests. Both per-pool and global completion
checks run before a successful result, and learned costs are saved only from a
successful default-branch push. Separate timing keys for different OS, interpreter,
dependency and service variants.

Use your actual pytest flags in the runner command. Tests that share a database,
queue, port or temporary path need per-shard isolation before enabling concurrency.
For custom collectors or nonstandard filenames, retain the existing discovery
contract and adapt the inventory instead of silently dropping those tests.

Benchmark 2/4/8 processes before requesting more runners. Compare time to gate,
setup/queue time and summed runner usage on the same revision. Larger runners
are paid even for public repositories. [Capacity and billing notes](../../docs/runners-and-diagnostics.md).

The [example execution test](../../tests/testing/test_shard_example.py) runs this
runner with real pytest and the actual planner/supervisor/completion verifier,
including a failing test and missing completion evidence.
