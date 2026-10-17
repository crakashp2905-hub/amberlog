"""Run the existing suite with every `Fabric` on Postgres instead of SQLite.

    MEMORY_FABRIC_TEST_PG=postgresql://... python -m pytest -p tests.pg_backend

Not a test module: a pytest plugin, loaded only when asked for. It replaces
the `EventLog` that `Fabric` opens with a `PostgresEventLog` on a schema
derived from the path, so

* `":memory:"` gets a fresh schema every time, as SQLite gives a fresh store;
* a file path gets the **same** schema every time it is opened, so a test that
  writes, closes and reopens is replaying from Postgres, not from a cache.

The point is to reuse a suite that already encodes what the product promises,
rather than write a second, smaller one for the new backend that would only
test what its author thought of. Tests that inspect the SQLite file itself --
its bytes, its `sqlite_master`, a `backup()` -- are expected to fail here, and
the result document lists them by cause rather than counting them as passes.
"""

from __future__ import annotations

import hashlib
import os
import uuid
from pathlib import Path
from typing import Any

import pytest

DSN = os.environ.get("MEMORY_FABRIC_TEST_PG")
_SCHEMAS: set[str] = set()


def _schema_for(path: Any) -> str:
    text = str(path)
    if text == ":memory:":
        return "m_" + uuid.uuid4().hex[:12]
    digest = hashlib.sha256(str(Path(text).resolve()).encode()).hexdigest()
    return "f_" + digest[:12]


def _open(path: Any = ":memory:", busy_timeout_ms: int = 5_000) -> Any:
    from memory_fabric.storage.postgres import PostgresEventLog

    schema = _schema_for(path)
    _SCHEMAS.add(schema)
    if str(path) != ":memory:":
        # The SQLite log creates parent directories and the file; tests that
        # check the store "exists" after creating it see a marker file.
        Path(str(path)).parent.mkdir(parents=True, exist_ok=True)
        Path(str(path)).touch(exist_ok=True)
    return PostgresEventLog(DSN, schema=schema)


def pytest_configure(config: pytest.Config) -> None:
    if not DSN:
        raise pytest.UsageError("tests.pg_backend needs MEMORY_FABRIC_TEST_PG")
    import memory_fabric.fabric as fabric

    fabric.EventLog = _open  # type: ignore[assignment]


def pytest_unconfigure(config: pytest.Config) -> None:
    if not DSN or not _SCHEMAS:
        return
    import psycopg

    with psycopg.connect(DSN, autocommit=True) as conn:
        for schema in sorted(_SCHEMAS):
            conn.execute(psycopg.sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE")
                         .format(psycopg.sql.Identifier(schema)))
