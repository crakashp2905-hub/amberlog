"""Append-only event log on SQLite.

The only writable table in the system. Everything else is derived (AGENTS.md
principle 3). Appends are transactional; `seq` is a monotonic integer that
defines the authoritative replay order.
"""

from __future__ import annotations

__stability__ = "stable"

from .dbtypes import Connection, Row

import json
import sqlite3
import time
from pathlib import Path
from typing import Iterable, Iterator

from . import pgcompat
from .events import Event
from .integrity import IntegrityChain
from .txn import depth as txn_depth
from .txn import forget as txn_forget
from .txn import transaction as txn_transaction

_SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    seq            INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id       TEXT    NOT NULL UNIQUE,
    ts             INTEGER NOT NULL,
    type           TEXT    NOT NULL,
    agent_id       TEXT,
    episode_id     TEXT,
    schema_version TEXT    NOT NULL,
    payload        TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_events_type    ON events(type);
CREATE INDEX IF NOT EXISTS idx_events_episode ON events(episode_id);

-- Guards against the one mutation the design forbids: rewriting history.
CREATE TRIGGER IF NOT EXISTS events_no_update
BEFORE UPDATE ON events
BEGIN
    SELECT RAISE(ABORT, 'event log is append-only');
END;
CREATE TRIGGER IF NOT EXISTS events_no_delete
BEFORE DELETE ON events
BEGIN
    SELECT RAISE(ABORT, 'event log is append-only');
END;
"""


class EventLog:
    """Append-only, replayable event store."""

    def __init__(
        self, path: str | Path = ":memory:", busy_timeout_ms: int = 5_000
    ) -> None:
        self.path = str(path)
        self._conn: Connection
        self.dialect = "sqlite"
        if pgcompat.is_postgres_url(self.path):
            # Optional backend; see pgcompat.py for what it changes and what it
            # does not. `path` is kept password-free because it is displayed.
            self._conn = pgcompat.connect(self.path, busy_timeout_ms=busy_timeout_ms)
            self.path = pgcompat.redact(self.path)
            self.dialect = "postgresql"
            self._conn.executescript(_SCHEMA)
            self.chain = IntegrityChain(self._conn)
            return
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        # `isolation_level=None` turns off sqlite3's implicit transaction
        # management so `transaction()` below owns every BEGIN and COMMIT. With
        # the default, a statement silently opens a transaction and any
        # `with conn:` exit commits it — which is how `request_retraction`
        # came to be non-atomic.
        conn = sqlite3.connect(
            self.path, check_same_thread=False, isolation_level=None
        )
        conn.row_factory = sqlite3.Row
        self._conn = conn
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        # Explicit, not a fix. The C library's default busy timeout is zero,
        # but Python's `sqlite3.connect` sets 5 seconds of its own accord, so
        # this store has always serialised concurrent writers rather than
        # failing on contention.
        #
        # Stated here anyway for two reasons: the value becomes visible and
        # configurable instead of inherited from a stdlib default that could
        # change, and a deployment that wants fail-fast behaviour can ask for
        # it. What it does **not** do is make SQLite multi-writer.
        #
        # Worth recording because I first wrote this comment claiming the
        # default was zero and that concurrent writers had been failing. They
        # had not. The falsification run — remove the pragma, expect the
        # contention test to fail — passed instead, which is how the claim got
        # caught before it reached a commit message.
        self._conn.execute(f"PRAGMA busy_timeout={busy_timeout_ms}")
        # NOT wrapped in `transaction()`: `executescript` issues its own
        # COMMIT before running, which would end ours and leave the
        # context manager committing a transaction that no longer exists.
        # Safe unwrapped because every statement is `IF NOT EXISTS` and,
        # with `isolation_level=None`, each autocommits.
        self._conn.executescript(_SCHEMA)
        # After the log's own schema, because it chains the rows that table
        # holds. Hash-chaining every append is the mechanism two earlier
        # security claims cited before it existed — see `integrity.py`.
        self.chain = IntegrityChain(self._conn)

    # --- transactions ----------------------------------------------------

    def transaction(self):
        """A transaction that **nests**, which `with conn:` does not.

        Delegates to `txn.transaction`, which keys the nesting depth by
        *connection* — because `EventLog`, `Outbox` and `ContentVault` share
        one connection precisely in order to share one transactional boundary,
        and a per-object counter would have each opening nested transactions
        unaware of the others. See that module for what this fixed.
        """
        return txn_transaction(self._conn)

    @property
    def in_transaction(self) -> bool:
        return txn_depth(self._conn) > 0

    # --- writing ---------------------------------------------------------

    def append(self, event: Event) -> Event:
        return self.append_many([event])[0]

    def append_many(self, events: Iterable[Event]) -> list[Event]:
        """Append atomically. Either every event lands or none does."""
        batch = list(events)
        if not batch:
            return []
        with self.transaction():
            stored: list[Event] = []
            for event in batch:
                cursor = self._conn.execute(
                    "INSERT INTO events (event_id, ts, type, agent_id, episode_id, schema_version, payload)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        event.event_id,
                        event.ts,
                        event.type,
                        event.agent_id,
                        event.episode_id,
                        event.schema_version,
                        json.dumps(event.payload, separators=(",", ":"), default=str),
                    ),
                )
                seq = cursor.lastrowid
                if seq is None:  # pragma: no cover - an INSERT always sets it
                    raise RuntimeError("the database assigned no sequence")
                stored.append(event.with_seq(int(seq)))
            # Inside the same transaction as the insert. Chaining separately
            # would leave a window in which an event exists unchained, and a
            # crash there would be indistinguishable from a deletion.
            self.chain.extend(stored, int(time.time() * 1000))
            return stored

    # --- reading ---------------------------------------------------------

    def read(self, since_seq: int = 0, limit: int | None = None) -> Iterator[Event]:
        """Replay in authoritative order, exclusive of `since_seq`."""
        sql = "SELECT * FROM events WHERE seq > ? ORDER BY seq ASC"
        params: list[object] = [since_seq]
        if limit is not None:
            sql += " LIMIT ?"
            params.append(limit)
        for row in self._conn.execute(sql, params):
            yield _row_to_event(row)

    def read_episode(self, episode_id: str) -> list[Event]:
        rows = self._conn.execute(
            "SELECT * FROM events WHERE episode_id = ? ORDER BY seq ASC", (episode_id,)
        )
        return [_row_to_event(r) for r in rows]

    def read_types(self, types: Iterable[str]) -> list[Event]:
        type_list = list(types)
        placeholders = ",".join("?" * len(type_list))
        rows = self._conn.execute(
            f"SELECT * FROM events WHERE type IN ({placeholders}) ORDER BY seq ASC", type_list
        )
        return [_row_to_event(r) for r in rows]

    @property
    def head_seq(self) -> int:
        row = self._conn.execute("SELECT COALESCE(MAX(seq), 0) AS s FROM events").fetchone()
        return int(row["s"]) if row is not None else 0

    def schema_versions(self) -> list[str]:
        """Every schema version that wrote into this log, oldest string first.

        A log is allowed to contain several: events are never rewritten, so a
        store that has outlived an upgrade carries the version of whatever was
        running at the time each event was appended. That is the point of
        keeping it per-event rather than per-store — the reader can tell which
        parts of the history it understands.
        """
        rows = self._conn.execute(
            "SELECT DISTINCT schema_version AS v FROM events ORDER BY v"
        )
        return [str(r["v"]) for r in rows]

    def __len__(self) -> int:
        row = self._conn.execute("SELECT COUNT(*) AS c FROM events").fetchone()
        return int(row["c"]) if row is not None else 0

    def close(self) -> None:
        # The transaction-depth entry is keyed by connection identity and a
        # closed connection's id can be reused by a later object, so dropping
        # it here is correctness rather than tidiness: a stale entry would
        # start a new log at a non-zero depth and its first `COMMIT` would
        # never run.
        txn_forget(self._conn)
        self._conn.close()


def _row_to_event(row: Row) -> Event:
    return Event(
        type=row["type"],
        ts=int(row["ts"]),
        payload=json.loads(row["payload"]),
        agent_id=row["agent_id"],
        episode_id=row["episode_id"],
        event_id=row["event_id"],
        schema_version=row["schema_version"],
        seq=int(row["seq"]),
    )
