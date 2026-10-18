"""PostgreSQL behind the slice of the `sqlite3` API this package uses.

Optional: needs `pip install "memory-fabric[postgres]"` (psycopg 3). The core
stays dependency-free; nothing imports this unless a store is opened with a
`postgresql://` URL.

**Why a shim and not a rewrite.** The event log, integrity chain, outbox, key
vault and revocation store all speak to one connection, and they share it on
purpose: one connection is one transaction boundary (see `txn.py`). Translating
at that connection keeps every module's SQL, transaction structure and tests
unchanged on SQLite, which remains the default and the reference. What changes
per dialect is confined here.

**What Postgres buys:** writers on several machines against one store, which
SQLite cannot do. **What it does not buy:** write throughput. Writers still
serialise -- on a table lock instead of a file lock -- because the hash chain
needs a total order and `seq` must stay gapless, which a Postgres sequence does
not guarantee (it skips values on rollback). Readers never block.

Translation, all of it:

* `?` placeholders become `%s`.
* DDL: `INTEGER` to `BIGINT` (timestamps are milliseconds), `BLOB` to `BYTEA`,
  the events table's `AUTOINCREMENT` to an explicit `seq` assigned as
  `MAX(seq)+1` under the write lock, other `AUTOINCREMENT` keys to `BIGSERIAL`,
  and SQLite `RAISE(ABORT, ...)` triggers to one Postgres trigger function.
* `BEGIN IMMEDIATE` becomes `BEGIN` plus `LOCK TABLE events IN EXCLUSIVE MODE`,
  which blocks other writers and no reader.
* `INSERT OR IGNORE` becomes `INSERT ... ON CONFLICT DO NOTHING`.
* `PRAGMA` statements and `sqlite_master` lookups map to their Postgres
  equivalent or to nothing. The outbox's 0.3.0 table migration finds no legacy
  tables, which is correct: no 0.3.0 store ever lived in Postgres.
* psycopg errors are re-raised as the `sqlite3` exception the callers already
  catch -- `IntegrityError` for a constraint or an append-only trigger,
  `OperationalError` for a lock timeout.
"""

from __future__ import annotations

__stability__ = "stable"

import re
import sqlite3
import threading
from typing import Any, Iterable, Iterator, Sequence
from urllib.parse import urlsplit, urlunsplit

try:  # pragma: no cover - exercised only where psycopg is installed
    import psycopg
    from psycopg import errors as pg_errors
except ImportError:  # pragma: no cover
    psycopg = None  # type: ignore[assignment]
    pg_errors = None  # type: ignore[assignment]

SCHEMES = ("postgresql://", "postgres://")

_APPEND_ONLY_FUNCTION = """
CREATE OR REPLACE FUNCTION mf_append_only() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION USING ERRCODE = 'integrity_constraint_violation',
                          MESSAGE = TG_ARGV[0];
END;
$$ LANGUAGE plpgsql
"""

_TRIGGER = re.compile(
    r"CREATE\s+TRIGGER\s+IF\s+NOT\s+EXISTS\s+(\w+)\s+BEFORE\s+(UPDATE|DELETE)\s+ON\s+(\w+)\s+"
    r"BEGIN\s+SELECT\s+RAISE\s*\(\s*ABORT\s*,\s*'([^']*)'\s*\)\s*;\s*END\s*;",
    re.IGNORECASE,
)
_EVENTS_INSERT = re.compile(r"^\s*INSERT INTO events \(", re.IGNORECASE)
# Serialises schema creation across processes: concurrent CREATE ... IF NOT
# EXISTS races in Postgres and fails one side with a duplicate-object error.
_SCHEMA_LOCK = 0x4D46_5343  # "MFSC"


def is_postgres_url(path: str) -> bool:
    return path.startswith(SCHEMES)


def redact(url: str) -> str:
    """The URL with any password removed, for display. Never log the real one."""
    parts = urlsplit(url)
    if parts.password is None:
        return url
    host = parts.hostname or ""
    if parts.port:
        host = f"{host}:{parts.port}"
    netloc = f"{parts.username}:***@{host}" if parts.username else f"***@{host}"
    return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))


class Row(tuple):
    """Indexable by position and by column name, like `sqlite3.Row`."""

    _index: dict[str, int]

    def __new__(cls, values: Sequence[Any], index: dict[str, int]) -> "Row":
        row = super().__new__(cls, values)
        row._index = index
        return row

    def __getitem__(self, key: Any) -> Any:  # type: ignore[override]
        if isinstance(key, str):
            return super().__getitem__(self._index[key])
        return super().__getitem__(key)

    def keys(self) -> list[str]:
        return list(self._index)


def _row_factory(cursor: Any):
    description = cursor.description or []
    index = {column.name: i for i, column in enumerate(description)}

    def make(values: Sequence[Any]) -> Row:
        return Row(_plain(values), index)

    return make


def _plain(values: Sequence[Any]) -> list[Any]:
    # BYTEA arrives as memoryview; the callers expect bytes, as from sqlite3.
    return [bytes(v) if isinstance(v, memoryview) else v for v in values]


class Cursor:
    """The handful of cursor attributes the callers read."""

    def __init__(self, rows: list[Row] | None = None, rowcount: int = -1,
                 lastrowid: int | None = None) -> None:
        self._rows = rows or []
        self.rowcount = rowcount
        self.lastrowid = lastrowid

    def fetchone(self) -> Row | None:
        return self._rows.pop(0) if self._rows else None

    def fetchall(self) -> list[Row]:
        rows, self._rows = self._rows, []
        return rows

    def __iter__(self) -> Iterator[Row]:
        while self._rows:
            yield self._rows.pop(0)


def _translate_error(exc: Exception) -> Exception:
    if pg_errors is not None:
        if isinstance(exc, pg_errors.IntegrityError):
            return sqlite3.IntegrityError(str(exc).strip())
        if isinstance(exc, (pg_errors.LockNotAvailable, pg_errors.QueryCanceled,
                            pg_errors.DeadlockDetected)):
            return sqlite3.OperationalError(f"database is locked: {str(exc).strip()}")
        if isinstance(exc, pg_errors.OperationalError):
            return sqlite3.OperationalError(str(exc).strip())
    return sqlite3.DatabaseError(str(exc).strip())


class PgConnection:
    """A psycopg connection presented as the `sqlite3.Connection` subset in use."""

    dialect = "postgresql"

    def __init__(self, url: str, busy_timeout_ms: int = 5_000) -> None:
        if psycopg is None:
            raise RuntimeError(
                "a postgresql:// store needs psycopg: pip install 'memory-fabric[postgres]'")
        self.url = url
        self._lock = threading.RLock()
        # A bounded connect. Without it the OS's TCP retry schedule decides how
        # long a mistyped URL hangs: 131 s against a closed port on Windows,
        # found by the 0.11.0 RC's Postgres acceptance run. A URL that sets its
        # own `connect_timeout` keeps it.
        extra = {} if "connect_timeout" in url else {"connect_timeout": CONNECT_TIMEOUT_S}
        try:
            self._pg = psycopg.connect(url, autocommit=True, **extra)
        except psycopg.Error as exc:
            # The message can echo the URL; never let a password through.
            raise sqlite3.OperationalError(
                f"cannot connect to {redact(url)}: {type(exc).__name__}") from None
        # A waiting writer gives up like SQLite's busy timeout does, instead of
        # hanging forever behind a crashed peer's lock.
        self._pg.execute(f"SET lock_timeout = {int(busy_timeout_ms)}")
        # Under the schema lock, and only if missing. Unguarded, every
        # connection replaced the function, and processes starting together
        # failed with "tuple concurrently updated" -- 5 of 80 simultaneous
        # connects in a local reproduction, and the CI postgres job.
        self._pg.execute("SELECT pg_advisory_lock(%s)", (_SCHEMA_LOCK,))
        try:
            exists = self._pg.execute(
                "SELECT 1 FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace "
                "WHERE p.proname = 'mf_append_only' AND n.nspname = current_schema()"
            ).fetchone()
            if not exists:
                self._pg.execute(_APPEND_ONLY_FUNCTION)
        finally:
            self._pg.execute("SELECT pg_advisory_unlock(%s)", (_SCHEMA_LOCK,))

    # --- the sqlite3.Connection subset ----------------------------------------

    def execute(self, sql: str, params: Iterable[Any] = ()) -> Cursor:
        with self._lock:
            return self._execute(sql, tuple(params))

    def executescript(self, script: str) -> None:
        with self._lock:
            self._pg.execute("SELECT pg_advisory_lock(%s)", (_SCHEMA_LOCK,))
            try:
                for statement in self._translate_script(script):
                    try:
                        self._pg.execute(statement)
                    except psycopg.Error as exc:
                        raise _translate_error(exc) from None
            finally:
                self._pg.execute("SELECT pg_advisory_unlock(%s)", (_SCHEMA_LOCK,))

    def rollback(self) -> None:
        """End any open transaction without applying it, like sqlite3's."""
        with self._lock:
            if self._pg.info.transaction_status != psycopg.pq.TransactionStatus.IDLE:
                self._pg.execute("ROLLBACK")

    def commit(self) -> None:
        with self._lock:
            if self._pg.info.transaction_status != psycopg.pq.TransactionStatus.IDLE:
                self._pg.execute("COMMIT")

    def close(self) -> None:
        with self._lock:
            if not self._pg.closed:
                self._pg.close()

    def backup(self, *_: Any, **__: Any) -> None:
        raise sqlite3.NotSupportedError(
            "backup of a PostgreSQL store is pg_dump's job: "
            "pg_dump --format=custom --file=<out> <database>")

    # --- translation ----------------------------------------------------------

    def _execute(self, sql: str, params: tuple[Any, ...]) -> Cursor:
        stripped = sql.strip()
        upper = stripped.upper()
        if upper.replace(" ", "") == "PRAGMABUSY_TIMEOUT":
            # The one PRAGMA with a Postgres meaning: how long a writer waits
            # for the lock, which this connection set as lock_timeout.
            return self._run(
                "SELECT setting::bigint FROM pg_settings WHERE name = 'lock_timeout'", ())
        if upper.startswith("PRAGMA"):
            return Cursor()
        if "SQLITE_MASTER" in upper:
            if "'TRIGGER'" in upper:
                sql = "SELECT tgname AS name FROM pg_trigger WHERE NOT tgisinternal"
                params = ()
            else:
                return Cursor()  # no legacy SQLite tables to migrate
        if upper == "BEGIN IMMEDIATE":
            self._run("BEGIN", ())
            # Writers serialise here, readers do not: EXCLUSIVE conflicts with
            # other writers' EXCLUSIVE and with row writes, never with SELECT.
            self._run("LOCK TABLE events IN EXCLUSIVE MODE", ())
            return Cursor()
        returning_seq = False
        if upper.startswith("INSERT OR IGNORE INTO"):
            sql = "INSERT INTO" + stripped[len("INSERT OR IGNORE INTO"):] + " ON CONFLICT DO NOTHING"
        elif _EVENTS_INSERT.match(stripped):
            # Gapless: assigned under the write lock that BEGIN IMMEDIATE took,
            # so no concurrent writer can read the same MAX.
            sql = (stripped.replace("INSERT INTO events (", "INSERT INTO events (seq, ", 1)
                   .replace("VALUES (", "VALUES ((SELECT COALESCE(MAX(seq), 0) + 1 FROM events), ", 1)
                   + " RETURNING seq")
            returning_seq = True
        return self._run(sql.replace("%", "%%").replace("?", "%s"), params,
                         returning_seq=returning_seq)

    def _run(self, sql: str, params: tuple[Any, ...], returning_seq: bool = False) -> Cursor:
        try:
            cur = self._pg.cursor(row_factory=_row_factory)
            cur.execute(sql, params)
            rows = cur.fetchall() if cur.description is not None else []
            rowcount = cur.rowcount
        except psycopg.Error as exc:
            raise _translate_error(exc) from None
        if returning_seq:
            return Cursor(rowcount=rowcount, lastrowid=int(rows[0][0]))
        return Cursor(rows, rowcount)

    @staticmethod
    def _translate_script(script: str) -> list[str]:
        triggers: list[str] = []

        def to_pg_trigger(match: re.Match[str]) -> str:
            name, when, table, message = match.groups()
            triggers.append(
                f"CREATE OR REPLACE TRIGGER {name} BEFORE {when.upper()} ON {table} "
                f"FOR EACH ROW EXECUTE FUNCTION mf_append_only('{message}')")
            return ""

        script = _TRIGGER.sub(to_pg_trigger, script)
        script = re.sub(r"--[^\n]*", "", script)
        script = re.sub(r"\bseq(\s+)INTEGER PRIMARY KEY AUTOINCREMENT",
                        r"seq\1BIGINT PRIMARY KEY", script)
        script = re.sub(r"\bINTEGER PRIMARY KEY AUTOINCREMENT\b", "BIGSERIAL PRIMARY KEY", script)
        script = re.sub(r"\bINTEGER\b", "BIGINT", script)
        script = re.sub(r"\bBLOB\b", "BYTEA", script)
        statements = [s.strip() for s in script.split(";") if s.strip()]
        return statements + triggers


CONNECT_TIMEOUT_S = 10
"""Seconds to wait for a Postgres server before giving up, unless the URL says."""


def connect(url: str, busy_timeout_ms: int = 5_000) -> PgConnection:
    return PgConnection(url, busy_timeout_ms=busy_timeout_ms)
