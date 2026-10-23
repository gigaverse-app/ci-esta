# Cache Python environments and recover safely

The `setup-cached-uv` composite extracts the useful environment-restore pattern
from Backend and AI without their private authentication or service policy.
It restores an exact `.venv`, repairs unusable restores and **always runs
`uv sync --locked`**. Cache contents accelerate installation; they never prove
that dependencies or tests are valid.

```yaml
- uses: actions/checkout@v7
- uses: gigaverse-app/ci-esta/setup-cached-uv@main
  with:
    python-version: '3.14'
    sync-args: --all-packages --only-group lint
- run: uv run --no-sync ruff check .
```

Use `working-directory` for another workspace and `cache-variant` for additional
system-library or container ABI inputs. The identity includes resolved Python
version/executable, OS, architecture, absolute workspace path, all discovered
uv locks/Python manifests, group/extra/install flags and the helper's own version.
Different dependency groups cannot share an exact environment accidentally.
There are no broad restore prefixes. Cache errors fall back to installation.

Successful default-branch push, schedule and manual-dispatch setup can save the shared environment cache.
PRs can restore it but cannot save into the shared default-branch scope. Package
download caching remains enabled. Private dependency authentication belongs in
the caller process; never cache credentials or token files inside `.venv`.

Supported sync flags cover groups, extras, packages and workspace installation.
The action deliberately rejects unlocked installs, alternate Python/project flags
and `--no-editable`: cached non-editable local source would require a separate
source-content identity. It validates the restored interpreter and prefix before
synchronization. A broken environment is removed within the workspace and rebuilt;
a `.venv` symlink is unlinked without deleting its external target.

## Measure before claiming a saving

Compare a cold default-branch push and a subsequent warm run with the same
interpreter, lock, group flags, runner image and workload. `cache-hit` records
the exact restore result. Keep restore, synchronization and save timings in the
CI-esta report; decompression can cost more than installation for tiny projects.
Use `cache-salt` for an isolated experiment, not a per-run production key.
Record job/run/attempt/head identities and include the cold cache save overhead.
Do not attribute test-selection savings to this cache.
