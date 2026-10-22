"""Clone an explicitly named migrated test database for pytest-django workers."""

import argparse
import os
from urllib.parse import urlsplit


def worker_databases(database: str, workers: int) -> list[str]:
    """Use pytest-django's xdist naming, rejecting ambiguous PostgreSQL truncation."""
    if not database.startswith("test_") or not 1 <= workers <= 32:
        raise ValueError("Expected an explicit test_ database and between 1 and 32 workers")
    names = [f"{database}_gw{worker}" for worker in range(workers)]
    if any(len(name.encode("utf-8")) > 63 for name in names):
        raise ValueError("Worker database names exceed PostgreSQL's 63-byte identifier limit")
    return names


def clone_test_database(database: str, workers: int) -> list[str]:
    """Replace only the named test database's worker copies, never the source.

    The caller owns migration, snapshot cache identity and worker count. This
    runs before workers start; no source connections may remain open. DATABASE_URL
    selects the server when present, otherwise libpq's PG* environment is used.
    """
    names = worker_databases(database, workers)
    import psycopg
    from psycopg import sql

    url = os.environ.get("DATABASE_URL")
    connection = urlsplit(url)._replace(path="/postgres").geturl() if url else "dbname=postgres"
    with psycopg.connect(connection, autocommit=True) as server:
        for name in names:
            server.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(name)))
            server.execute(
                sql.SQL("CREATE DATABASE {} TEMPLATE {}").format(sql.Identifier(name), sql.Identifier(database))
            )
    return names


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", required=True, help="Migrated test_ database, disconnected before cloning")
    parser.add_argument("--workers", required=True, type=int)
    args = parser.parse_args()
    print("Prepared " + ", ".join(clone_test_database(args.database, args.workers)))
    return 0
