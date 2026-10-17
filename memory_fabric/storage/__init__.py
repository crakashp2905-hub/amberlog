"""Storage backends for the event log.

The SQLite `EventLog` in `memory_fabric.eventlog` is the default and needs no
dependencies. `postgres.PostgresEventLog` is the multi-writer backend and needs
`psycopg`, which is an optional extra: importing this package does not import
it, so the core stays dependency-free.
"""

from __future__ import annotations

from pathlib import Path


def is_postgres_dsn(path: "str | Path") -> bool:
    """Whether a `--db` value names a Postgres database rather than a file.

    By URI scheme only. A keyword DSN (`host=... dbname=...`) is not
    recognised, because a file of that name is a legal SQLite path and
    guessing between the two would open the wrong store.
    """
    return isinstance(path, str) and path.startswith(
        ("postgresql://", "postgres://"))


def store_exists(path: "str | Path") -> bool:
    """Whether opening `path` would open a store rather than create one.

    For a file, that it exists. For a Postgres DSN, that the database already
    holds an event log -- connecting succeeds against any empty database, so
    reachability alone would let a typo create a store silently, the failure
    the CLI's `--create` guard exists to prevent.
    """
    if str(path) == ":memory:":
        return True
    if is_postgres_dsn(path):
        from .postgres import has_event_log

        return has_event_log(str(path))
    return Path(path).exists()


def display(path: "str | Path") -> str:
    """`path` as it may be printed: a DSN with its password removed."""
    if is_postgres_dsn(path):
        from .postgres import redact

        return redact(str(path))
    return str(path)
