# Measured dependency, build and tool caches

## Bun dependency downloads

`setup-cached-bun` installs the version in `.bun-version`, restores Bun's package
download cache, and always runs `bun install --frozen-lockfile`. Configure private
registry credentials and SSH in the caller before invoking it. It uses the cache
directory returned by `bun pm cache`, including `BUN_INSTALL_CACHE_DIR` overrides.

```yaml
- uses: actions/checkout@v7
- uses: gigaverse-app/ci-esta/actions/setup-cached-bun@v1
- run: bun test
```

The key includes OS, architecture, resolved Bun version, patch files, lockfiles
and package manifests. `node_modules` is excluded from manifest hashing. Older
keys with the same platform, runtime, patches and optional `cache-salt` can supply
downloads; the locked install remains mandatory. Successful installation saves
new download entries immediately, even if a later test fails. Cache service
failures fall back to installation; failed installation still fails the job.

Each setup publishes a `ci-esta/cache-operation/v1` artifact with the source
run/attempt/head, exact or fallback hit, miss, skipped or unavailable outcome,
restore/save elapsed times and locked-install result/time. These are package
downloads, not a validated complete environment or evidence of passing tests.
The separate cache of the Bun executable maintained by `setup-bun` is outside
these dependency-cache measurements. Timings bracket action boundaries and include
small step-transition overhead. A skipped save remains unavailable, not zero.

Use `working-directory` for another lockfile location and `bun-version-file` for
another version file. Multiple calls in one job need distinct `measurement-name`
values. Matrix jobs should set `job-name` to their exact displayed Actions name.
`cache-salt` provides an isolated namespace for cold/warm experiments.
Set `cache-downloads: 'false'` when fresh downloads beat archive transfer and
extraction, or when a runner already supplies a persistent package cache. The
locked install and its measurements still run; restore/save are reported as
skipped. This switch does not delete a runner's existing local cache.

Download caching is the portable default. Expanded `node_modules` trees can be
larger, contain native build output, and depend on lifecycle scripts and the
runner's system libraries. Measure both paths before adding an installed-tree
cache through `report-cache`; include mandatory installation and archive costs.
For custom installation flags or cache policies, compose `setup-bun`, your own
locked installation and `report-cache` instead of weakening the shared action's
frozen-install contract.

## Other download, build and tool caches

For caches outside dependency setup, keep the caller's validation and save policy
and publish the native restore outputs with `report-cache`:

```yaml
- name: Restore compiler state
  id: compiler
  uses: actions/cache/restore@v5
  with:
    path: build
    key: compiler-${{ runner.os }}-${{ github.sha }}
    restore-keys: compiler-${{ runner.os }}-
- run: bun run typecheck
- name: Save compiler state
  if: ${{ success() && steps.compiler.outputs.cache-hit != 'true' }}
  uses: actions/cache/save@v5
  with:
    path: build
    key: ${{ steps.compiler.outputs.cache-primary-key }}
- uses: gigaverse-app/ci-esta/actions/report-cache@v1
  if: always()
  continue-on-error: true
  with:
    name: Compiler state
    kind: build
    restore-outcome: ${{ steps.compiler.outcome }}
    cache-hit: ${{ steps.compiler.outputs.cache-hit }}
    primary-key: ${{ steps.compiler.outputs.cache-primary-key }}
    matched-key: ${{ steps.compiler.outputs.cache-matched-key }}
    restore-step: Restore compiler state
    save-step: Save compiler state
```

Use `kind: download`, `build` or `tool`. A fallback hit requires a matched key;
`cache-hit: false` alone cannot establish one. The observer matches exact job
and step names in the same run attempt to obtain restore/save timings, including
saves after publication. Missing, ambiguous and skipped steps stay unmeasured.
Cache keys are consumed to classify the restore but are not retained in reports.

Reporting failures do not gate validation. Cache overhead is already included in
job time. Hits do not establish time saved; that requires a comparable cold run.

## Python environments

The `setup-cached-uv` composite extracts the useful environment-restore pattern
from Backend and AI without their private authentication or service policy.
It restores an exact `.venv`, repairs unusable restores and **always runs
`uv sync --locked`**. Cache contents accelerate installation; they never prove
that dependencies or tests are valid.

```yaml
- uses: actions/checkout@v7
- uses: gigaverse-app/ci-esta/actions/setup-cached-uv@v1
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
