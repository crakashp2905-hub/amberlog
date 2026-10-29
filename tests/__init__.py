"""Optional: run the whole suite against PostgreSQL.

    MF_TEST_POSTGRES_URL=postgresql://user@host:5432/db python -m unittest discover -s tests -t .

With the variable set, every in-memory store a test creates (`":memory:"`, the
default) is backed by a fresh Postgres schema instead, so the existing
assertions exercise the Postgres backend rather than a separate, smaller set of
tests written for it. File-path stores stay on SQLite: those tests are about
files. Without the variable this does nothing, and the suite runs with nothing
installed, as CI requires.
"""

from __future__ import annotations

import atexit
import itertools
import os

_URL = os.environ.get("MF_TEST_POSTGRES_URL")

if _URL:  # pragma: no cover - only under the Postgres CI job
    import psycopg

    from amberlog import eventlog

    _counter = itertools.count()
    _schemas: list[str] = []
    _original_init = eventlog.EventLog.__init__

    def _schema_url(schema: str) -> str:
        separator = "&" if "?" in _URL else "?"
        return f"{_URL}{separator}options=-csearch_path%3D{schema}"

    def _init(self, path=":memory:", busy_timeout_ms: int = 5_000) -> None:
        if str(path) == ":memory:":
            schema = f"mf_t{os.getpid()}_{next(_counter)}"
            with psycopg.connect(_URL, autocommit=True) as conn:
                conn.execute(f"CREATE SCHEMA {schema}")
            _schemas.append(schema)
            path = _schema_url(schema)
        _original_init(self, path, busy_timeout_ms)

    eventlog.EventLog.__init__ = _init  # type: ignore[method-assign]

    @atexit.register
    def _drop_schemas() -> None:
        if not _schemas:
            return
        with psycopg.connect(_URL, autocommit=True) as conn:
            for schema in _schemas:
                conn.execute(f"DROP SCHEMA IF EXISTS {schema} CASCADE")
