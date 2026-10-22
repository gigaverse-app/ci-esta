# Shorten the jobs that block the gate

Start with `ci-esta report --critical-path --gate 'Validation gate'`, retaining
the source run, attempt and commit. Compare step times inside the blocking job.
Dependency setup is not automatically the bottleneck: Due's measured minimum
Django lane spent 87 seconds on package controls and 261 seconds on integration
tests, while setup took 8 seconds (run 39865607407).

## Parallel Django tests without repeating migrations

Migrate or restore one **disposable test database**, then disconnect from it.
Install `ci-esta[postgres]` in your tooling environment and run:

```sh
ci-esta-postgres-clone --database test_wagtail_tasks --workers 4
pytest -n 4 --dist worksteal --reuse-db --junitxml=results.xml
```

The command uses `DATABASE_URL`, or libpq's `PGHOST`, `PGPORT`, `PGUSER` and
`PGPASSWORD`. It replaces only `test_wagtail_tasks_gw0` through `gw3`, using
PostgreSQL template databases. It leaves the source intact and rejects names
that PostgreSQL would truncate. Do this before starting workers, on an isolated
CI server. Match the worker count to pytest-django's default xdist naming.

The caller owns migration settings and snapshot cache keys. Include the lock,
settings and migration code in those keys. A cache hit does not prove tests ran.
Keep required-case validators after pytest and use plugins that merge actual
worker outcomes into controller reports. Do not parallelize suites sharing
fixed ports, global queues, singleton resources or a database without isolating
those resources first. All tests and negative controls still run.

## Avoid a redundant Git launcher on Windows

Git for Windows can expose `bin/git.exe` or `cmd/git.exe`, which launches the
native executable. For suites creating many temporary Git repositories, use:

```yaml
- uses: gigaverse-app/ci-esta/.github/actions/native-windows-git@<reviewed-commit>
- run: uv run --locked pytest -n 4 --cov
```

The action verifies that the native executable reports exactly the same Git
version before adding its directory to PATH. Unrecognized layouts keep the
existing Git. It changes neither Git configuration nor test/coverage policy.
This implementation originates in pytest-selective PR #26.

Keep raw before/after CI reports and JUnit. Compare the same suite, Python,
platform, coverage and dependency policy. Report gate elapsed time separately
from execution critical path and runner-seconds; hosted scheduling variation is
not a test speedup. Parallel work can reduce latency while increasing runner
cost. Retain the change only when its measured tradeoff is useful.
