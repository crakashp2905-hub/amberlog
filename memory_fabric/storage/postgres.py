"""The event log on PostgreSQL, with many writers and one history.

## Why this is not a driver swap

The SQLite `EventLog` gets two guarantees for free from having exactly one
writer, and a naive Postgres port loses both **silently** -- every test that
writes from one thread still passes.

**1. Sequence numbers in commit order, with no gaps.** SQLite's `seq` is a
rowid assigned under a database-wide write lock, so it is gapless and commit
order equals sequence order. A Postgres `BIGSERIAL` is neither. A rolled-back
transaction burns a value, leaving a gap; worse, two transactions can take
sequence 5 and 6 and commit in the order 6, 5. A reader polling
`read(since_seq=4)` between those commits sees event 6, advances its cursor to
6, and **never replays event 5**. For an event-sourced system whose
projections are rebuilt from the log, that is permanent, unannounced data
loss in every downstream projection -- and the log itself looks fine.

**2. One linear hash chain.** `IntegrityChain.extend` reads the current head
and links new events onto it. Two concurrent writers both read head H4, both
compute H5, and the chain forks; verification then fails on a store where
nothing was tampered with, which is the false alarm that teaches an operator
to ignore the check.

## The design: serialise the append, not the store

Every append takes a row lock on a single `log_head` row with
`SELECT ... FOR UPDATE`, and assigns sequence numbers from it:

    BEGIN
      SELECT seq, chain_digest FROM log_head WHERE id = 1 FOR UPDATE   -- waits here
      INSERT INTO events          (seq = head + 1 ...)
      INSERT INTO integrity_chain (link onto head ...)
      UPDATE log_head SET seq = ..., chain_digest = ...
    COMMIT                                                              -- lock released

`FOR UPDATE` holds the lock until commit, so the next appender cannot read the
head until this transaction is visible. Sequence numbers are therefore
assigned in commit order and are gapless -- a rollback rolls the head back too
-- and the chain is linear because each appender links onto a committed head.

**What this costs, stated rather than hidden:** appends serialise on one row.
Many processes and hosts can write, readers are fully concurrent and never
block on writers, but two appends never overlap. For an append-only,
hash-chained log that is the correct trade: a parallel append path would have
to give up either gapless commit order or the chain, and both are guarantees
the rest of the system is built on.

Measured (`experiments/pg_throughput.py`, single-event transactions, one
connection per writer, a local Postgres 16 on the same laptop):

| writers | SQLite | Postgres |
|---|---|---|
| 1 | 1,081/s | 657/s |
| 2 | 1,332/s | 694/s |
| 4 | 585/s | 769/s |
| 8 | 463/s | 720/s |

An earlier draft of this docstring said a hot row lock was "good for
thousands of transactions a second". It was not measured and it was wrong by
about an order of magnitude on this hardware, which is the reason this table
exists.

What the table actually says is narrower and more useful. **SQLite is faster
with one or two writers**, because a Postgres transaction costs a round trip
and more bookkeeping. **SQLite then degrades** -- 65% down from its peak by
eight writers, as writers spin on the file lock -- while **Postgres stays flat**
and is ahead from four writers up. Postgres p50 latency rises with writers
(1.3 ms to 10.3 ms) because appenders queue on the lock, which is the cost of
the guarantee. Around 700 appends a second is far above what memory writes
need: an agent writes a memory per decision, not per millisecond.

So the case for this backend is not speed. It is many processes and hosts
writing one log, throughput that holds under contention instead of falling,
and Postgres's own replication and backup -- with the ordering and chain
guarantees intact, which a naive port does not keep.

Alternatives considered and rejected:

* `SERIALIZABLE` isolation detects the conflict, but by **aborting** one
  transaction with a serialization failure, which every caller would then
  have to retry. Blocking on a row lock gets the same ordering with no retry
  path to get wrong.
* `pg_advisory_xact_lock` serialises too, but the head row is needed anyway --
  it holds the sequence and the chain head -- and `FOR UPDATE` on it takes the
  lock and reads the data in one statement.
* `BIGSERIAL` plus a "low-water mark" read rule is how some event stores cope
  with out-of-order commits, at the cost of readers that must hold back until
  every lower sequence is known to be committed or abandoned. That moves a
  correctness obligation onto every reader, and this one has several.

## The payload is stored as text, exactly as SQLite stores it

Not `jsonb`, though `jsonb` is the idiomatic choice. Two reasons, either
sufficient. The integrity chain hashes the canonical form of the *decoded*
payload, so the source of truth must round-trip without the backend altering
what is decoded. And `jsonb` **rejects `Infinity` and `NaN`**, which
`json.dumps` emits for non-finite floats and which this project's history
records reaching an event payload; SQLite's `TEXT` accepts them, so a `jsonb`
column would make the same event appendable on one backend and not the other.
The event log never queries inside payloads, so `jsonb` buys nothing here.

## Append-only is enforced by the database

Triggers refuse `UPDATE` and `DELETE` on `events` and `integrity_chain`, as the
SQLite log's do, and a statement-level trigger refuses `TRUNCATE` -- which
does not fire row triggers, and which SQLite does not have, so a straight port
of the SQLite schema leaves the log one statement from deletion. The table
owner can still disable triggers, exactly as anyone with write access to the
SQLite file can drop them; that is the same threat model, and the hash chain is
what makes such a tamper visible afterwards.

## Verification is shared, not reimplemented

`verify()` loads the recorded links and calls `integrity.verify_records` -- the
same algorithm `IntegrityChain.verify` uses, extracted so that both backends
are checked by one definition of "intact". Two backends verified by two
algorithms could each pass their own check while disagreeing about what it
means.

## Scope

This is the event log: the source of truth, and the part where concurrency is
a correctness problem rather than a throughput one. The outbox, content vault
and identity tables still live in SQLite, which also means the property that
`EventLog`, `Outbox` and `ContentVault` share one transaction is not yet
available on Postgres. Porting them is the next pass.
"""

from __future__ import annotations

import json
import threading
import time
from contextlib import contextmanager
from typing import Any, Iterable, Iterator

from ..events import Event
from ..integrity import GENESIS, Verification, event_digest, link, verify_records

SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    seq            BIGINT  PRIMARY KEY,
    event_id       TEXT    NOT NULL UNIQUE,
    ts             BIGINT  NOT NULL,
    type           TEXT    NOT NULL,
    agent_id       TEXT,
    episode_id     TEXT,
    schema_version TEXT    NOT NULL,
    payload        TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_events_type    ON events(type);
CREATE INDEX IF NOT EXISTS idx_events_episode ON events(episode_id);

CREATE TABLE IF NOT EXISTS integrity_chain (
    seq           BIGINT PRIMARY KEY REFERENCES events(seq),
    event_digest  TEXT   NOT NULL,
    chain_digest  TEXT   NOT NULL,
    recorded_ms   BIGINT NOT NULL
);

-- The single row every append locks. Holding the sequence and the chain head
-- here, rather than deriving them with MAX(), is what makes one locked read
-- give the appender everything it needs.
CREATE TABLE IF NOT EXISTS log_head (
    id            SMALLINT PRIMARY KEY CHECK (id = 1),
    seq           BIGINT   NOT NULL,
    chain_digest  TEXT     NOT NULL
);

-- Append-only, enforced by the database and not only by convention, to match
-- the SQLite log's `events_no_update` / `events_no_delete` triggers. The chain
-- is tamper-EVIDENT; these make a tamper need privileges the application
-- should not hold, which is the layer underneath it.
CREATE OR REPLACE FUNCTION mf_append_only() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION '% is append-only', TG_TABLE_NAME
        USING ERRCODE = 'restrict_violation';
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE TRIGGER events_append_only
    BEFORE UPDATE OR DELETE ON events
    FOR EACH ROW EXECUTE FUNCTION mf_append_only();
CREATE OR REPLACE TRIGGER integrity_chain_append_only
    BEFORE UPDATE OR DELETE ON integrity_chain
    FOR EACH ROW EXECUTE FUNCTION mf_append_only();

-- TRUNCATE does not fire row-level triggers, so without these the whole log is
-- one statement from deletion while every row trigger above stays silent.
-- SQLite has no TRUNCATE -- an unqualified DELETE fires row triggers -- which
-- is why its schema needs no counterpart and why a straight port misses this.
CREATE OR REPLACE TRIGGER events_no_truncate
    BEFORE TRUNCATE ON events
    FOR EACH STATEMENT EXECUTE FUNCTION mf_append_only();
CREATE OR REPLACE TRIGGER integrity_chain_no_truncate
    BEFORE TRUNCATE ON integrity_chain
    FOR EACH STATEMENT EXECUTE FUNCTION mf_append_only();

-- log_head is deliberately left writable: every append updates it. It holds
-- no history -- verification reads events and integrity_chain, never the
-- head -- so moving it does not falsify the record. Setting it below the true
-- head makes the next append collide on the primary key and fail loudly;
-- setting it above leaves a gap, which the conformance suite detects. The
-- deployment control is privilege separation: the application role needs
-- INSERT on events and integrity_chain and UPDATE on log_head, and nothing
-- more.
"""


def _psycopg() -> Any:
    try:
        import psycopg  # type: ignore
    except ImportError as exc:  # pragma: no cover - optional dependency
        raise RuntimeError(
            "PostgresEventLog needs psycopg, which the core does not depend "
            "on. Install it where you need Postgres: pip install "
            "'psycopg[binary]'") from exc
    return psycopg


class PostgresEventLog:
    """An append-only, replayable, hash-chained event store on PostgreSQL.

    The same public surface as `memory_fabric.eventlog.EventLog`, so it can be
    exercised by the same conformance suite. One instance holds one
    connection; open one per thread or process, which is how Postgres is meant
    to be used and is what the concurrency tests do.
    """

    def __init__(self, dsn: str, schema: str | None = None,
                 lock_timeout_ms: int = 10_000) -> None:
        psycopg = _psycopg()
        self.dsn = dsn
        self.schema = schema
        # Autocommit, so that `transaction()` owns every BEGIN and COMMIT --
        # the same reason the SQLite log sets `isolation_level=None`. With
        # psycopg's default, the first statement opens a transaction nobody
        # asked for and it stays open until something commits it.
        self._conn = psycopg.connect(dsn, autocommit=True)
        self._depth = 0
        self._local = threading.local()
        if schema:
            # Quoted as an identifier, never interpolated as text.
            self._conn.execute(
                psycopg.sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(
                    psycopg.sql.Identifier(schema)))
            self._conn.execute(
                psycopg.sql.SQL("SET search_path TO {}").format(
                    psycopg.sql.Identifier(schema)))
        # Bounded, so a wedged appender produces an error rather than a
        # silent hang in every other writer behind it.
        self._conn.execute(f"SET lock_timeout = {int(lock_timeout_ms)}")
        with self._conn.transaction():
            # Serialise schema bootstrap across every process opening this
            # schema. Found by the conformance suite, not by reasoning: eight
            # handles opened at once all ran `CREATE OR REPLACE FUNCTION` on the
            # same `pg_proc` row and Postgres reported a deadlock. One process
            # never sees it; a deployment whose workers start together against
            # a fresh database does, on its first boot.
            #
            # Transaction-scoped, so it is released at commit and cannot leak
            # if a process dies mid-bootstrap. Keyed by schema, so stores in
            # different schemas do not wait on each other. Everything after the
            # first holder finds the objects present and is a cheap no-op.
            self._conn.execute(
                "SELECT pg_advisory_xact_lock(hashtext(%s))",
                ("memory_fabric.schema:" + (schema or "public"),))
            self._conn.execute(SCHEMA)
            self._conn.execute(
                "INSERT INTO log_head (id, seq, chain_digest) VALUES (1, 0, %s) "
                "ON CONFLICT (id) DO NOTHING", (GENESIS,))

    # --- transactions -----------------------------------------------------

    @contextmanager
    def transaction(self) -> Iterator[None]:
        """A transaction that nests, via psycopg's savepoints."""
        self._depth += 1
        try:
            with self._conn.transaction():
                yield
        finally:
            self._depth -= 1

    @property
    def in_transaction(self) -> bool:
        return self._depth > 0

    # --- writing ----------------------------------------------------------

    def append(self, event: Event) -> Event:
        return self.append_many([event])[0]

    def append_many(self, events: Iterable[Event]) -> list[Event]:
        """Append atomically, in commit order, onto one linear chain."""
        batch = list(events)
        if not batch:
            return []
        now_ms = int(time.time() * 1000)
        with self.transaction():
            row = self._conn.execute(
                "SELECT seq, chain_digest FROM log_head WHERE id = 1 FOR UPDATE"
            ).fetchone()
            seq, previous = int(row[0]), str(row[1])
            stored: list[Event] = []
            for event in batch:
                seq += 1
                placed = event.with_seq(seq)
                self._conn.execute(
                    "INSERT INTO events (seq, event_id, ts, type, agent_id, "
                    "episode_id, schema_version, payload) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                    (seq, placed.event_id, placed.ts, str(placed.type),
                     placed.agent_id, placed.episode_id,
                     placed.schema_version,
                     # Byte-identical to the SQLite log: compact, sorted by
                     # nothing, `default=str` for the same values.
                     json.dumps(placed.payload, separators=(",", ":"),
                                default=str)))
                digest = event_digest(placed)
                previous = link(previous, digest)
                self._conn.execute(
                    "INSERT INTO integrity_chain (seq, event_digest, "
                    "chain_digest, recorded_ms) VALUES (%s, %s, %s, %s)",
                    (seq, digest, previous, now_ms))
                stored.append(placed)
            self._conn.execute(
                "UPDATE log_head SET seq = %s, chain_digest = %s WHERE id = 1",
                (seq, previous))
            return stored

    # --- reading ----------------------------------------------------------

    def read(self, since_seq: int = 0,
             limit: int | None = None) -> Iterator[Event]:
        """Replay in authoritative order, exclusive of `since_seq`.

        Correct under concurrent appends *because of* the append lock: no
        event with a lower sequence can commit after a higher one is visible,
        so a cursor that advances past what it has read never skips anything.
        """
        sql = ("SELECT seq, event_id, ts, type, agent_id, episode_id, "
               "schema_version, payload FROM events WHERE seq > %s "
               "ORDER BY seq ASC")
        params: list[Any] = [since_seq]
        if limit is not None:
            sql += " LIMIT %s"
            params.append(limit)
        for row in self._conn.execute(sql, params).fetchall():
            yield _row_to_event(row)

    def read_episode(self, episode_id: str) -> list[Event]:
        rows = self._conn.execute(
            "SELECT seq, event_id, ts, type, agent_id, episode_id, "
            "schema_version, payload FROM events WHERE episode_id = %s "
            "ORDER BY seq ASC", (episode_id,)).fetchall()
        return [_row_to_event(r) for r in rows]

    def read_types(self, types: Iterable[str]) -> list[Event]:
        type_list = [str(t) for t in types]
        if not type_list:
            return []
        rows = self._conn.execute(
            "SELECT seq, event_id, ts, type, agent_id, episode_id, "
            "schema_version, payload FROM events WHERE type = ANY(%s) "
            "ORDER BY seq ASC", (type_list,)).fetchall()
        return [_row_to_event(r) for r in rows]

    @property
    def head_seq(self) -> int:
        row = self._conn.execute(
            "SELECT seq FROM log_head WHERE id = 1").fetchone()
        return int(row[0])

    def schema_versions(self) -> list[str]:
        rows = self._conn.execute(
            "SELECT DISTINCT schema_version FROM events ORDER BY 1").fetchall()
        return [str(r[0]) for r in rows]

    def __len__(self) -> int:
        return int(self._conn.execute(
            "SELECT COUNT(*) FROM events").fetchone()[0])

    # --- integrity --------------------------------------------------------

    def verify(self) -> Verification:
        """Verify the chain with the algorithm the SQLite log uses."""
        records = {
            int(r[0]): (str(r[1]), str(r[2]))
            for r in self._conn.execute(
                "SELECT seq, event_digest, chain_digest FROM integrity_chain "
                "ORDER BY seq").fetchall()
        }
        return verify_records(records, self.read())

    def close(self) -> None:
        self._conn.close()


def _row_to_event(row: Any) -> Event:
    seq, event_id, ts, kind, agent_id, episode_id, schema_version, payload = row
    # Field for field as `eventlog._row_to_event`, so an event read back from
    # either backend is the same object and has the same digest.
    return Event(
        type=kind, ts=int(ts), payload=json.loads(payload),
        agent_id=agent_id, episode_id=episode_id, event_id=event_id,
        schema_version=schema_version, seq=int(seq),
    )
