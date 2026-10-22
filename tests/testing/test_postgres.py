"""Worker isolation and SQL boundaries for a real PostgreSQL template protocol."""

import pytest

from ci_esta.testing.postgres import clone_test_database, worker_databases


@pytest.mark.parametrize(
    "name,workers", [("production", 4), ("test_app", 0), ("test_app", 33), ("test_" + "é" * 30, 4)]
)
def test_invalid_names_fail_before_connecting(name, workers):
    with pytest.raises(ValueError):
        clone_test_database(name, workers)


def test_worker_names_match_pytest_django_without_truncation():
    assert worker_databases("test_wagtail_tasks", 4) == [f"test_wagtail_tasks_gw{i}" for i in range(4)]
    assert len(worker_databases("test_" + "a" * 54, 1)[0]) == 63


def test_clone_uses_quoted_identifiers_and_preserves_the_source(monkeypatch):
    import psycopg

    calls = []
    statements = []

    class Server:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def execute(self, statement):
            statements.append(statement.as_string())

    def connect(connection, **kwargs):
        calls.append((connection, kwargs))
        return Server()

    monkeypatch.setattr(psycopg, "connect", connect)
    monkeypatch.setenv("DATABASE_URL", "postgresql://localhost/app?sslmode=require")
    assert clone_test_database('test_a"b', 1) == ['test_a"b_gw0']
    assert calls == [("postgresql://localhost/postgres?sslmode=require", {"autocommit": True})]
    assert statements == [
        'DROP DATABASE IF EXISTS "test_a""b_gw0" WITH (FORCE)',
        'CREATE DATABASE "test_a""b_gw0" TEMPLATE "test_a""b"',
    ]
