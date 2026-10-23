# Keep cached PostgreSQL databases portable

Match the client major version to the test service. A hosted runner can upgrade
`pg_restore` independently of your `postgres:16` service. New clients can emit
settings such as `transaction_timeout` that an older server rejects before any
test runs.

```yaml
services:
  postgres:
    image: postgres:16
# Under the job's steps, after checkout:
steps:
  - uses: gigaverse-app/ci-esta/actions/postgres-client@main
    with:
      image: postgres:16
  - run: pg_dump --format=custom --file "$RUNNER_TEMP/database.dump" "$DATABASE_URL"
```

Use the same image (or immutable digest) for client and server. This Linux-only
action puts Docker-backed `pg_dump`, `pg_restore`, and `psql` on PATH. It reuses
the service image already pulled by Actions. Commands retain their arguments,
working directory, and PG environment variables. Workspace and runner temporary
paths are mounted at their original locations; put dumps and certificate files
there. The container runs as the caller's UID, so created dumps remain writable.
It requires Docker and host networking; it is not for Windows or macOS runners.

Include the PostgreSQL major version, migration inputs and preparation code in
the snapshot cache key. Bump the key when adopting a matched client: an old
archive may have been written by a newer incompatible client. A cache remains
an optimization; regenerate an unreadable snapshot from migrations in a fresh
test database. Never restore a test snapshot over production data.
