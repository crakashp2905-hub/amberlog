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
import sys
from pathlib import Path

# Source tests intentionally exercise the checkout. Packaging acceptance clears
# these variables and runs in a separate directory against an installed wheel.
_SOURCE = str(Path(__file__).resolve().parents[1] / "src")
sys.path.insert(0, _SOURCE)
os.environ["PYTHONPATH"] = _SOURCE + (os.pathsep + os.environ["PYTHONPATH"]
                                     if os.environ.get("PYTHONPATH") else "")

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
