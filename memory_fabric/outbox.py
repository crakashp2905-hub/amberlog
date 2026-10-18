"""Transactional outbox and recipient inbox.

Invariant 3: *a committed retraction cannot disappear because a process crashes
before dispatch.* The old code could not satisfy it — `propagate_retraction`
committed the local quarantine and then looped over live target objects in the
same call, so a crash between those two acts lost the dispatch with **no record
that it was owed**.

The fix is the standard one and the reason it works here is cheap: the outbox
and the event log live in **the same SQLite file**, so "append the event and
record the intent atomically" is one `BEGIN`. The moment they are split across
two systems the dual-write problem appears and has to be solved explicitly
rather than hoped past, which is a reason to keep them together as long as
possible (roadmap §1.3, §6.1).

Delivery is **at-least-once plus idempotent processing**. Exactly-once network
delivery is not available and is not assumed. The recipient deduplicates on
`(origin_store_id, retraction_id)` — event identity, not state convergence,
because a replay and a genuinely new second retraction of the same memory are
different events.
"""

from __future__ import annotations

from .dbtypes import Connection, Row

import json
import time
from dataclasses import dataclass
from typing import Sequence

from .protocol import (
    Acknowledgement,
    PropagationState,
    Retraction,
    SETTLED_STATES,
    can_transition,
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS outbox (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    retraction_id   TEXT    NOT NULL,
    recipient       TEXT    NOT NULL,
    payload         TEXT    NOT NULL,
    target_key      TEXT    NOT NULL DEFAULT '',
    state           TEXT    NOT NULL,
    attempts        INTEGER NOT NULL DEFAULT 0,
    last_attempt_ms INTEGER,
    next_attempt_ms INTEGER NOT NULL DEFAULT 0,
    last_error      TEXT,
    updated_ms      INTEGER NOT NULL,
    -- One row per campaign, recipient and hop target. A store that holds
    -- two copies of the same origin memory owes its peers a retraction
    -- for each, and they are different deliveries.
    UNIQUE (retraction_id, recipient, target_key)
);
CREATE INDEX IF NOT EXISTS outbox_due ON outbox (state, next_attempt_ms);

CREATE TABLE IF NOT EXISTS inbox (
    origin_store_id TEXT    NOT NULL,
    retraction_id   TEXT    NOT NULL,
    -- Which copy this row is the outcome for: see Retraction.dedupe_key.
    target_key      TEXT    NOT NULL DEFAULT '',
    origin_sequence INTEGER NOT NULL,
    outcome         TEXT    NOT NULL,
    detail          TEXT    NOT NULL DEFAULT '',
    received_ms     INTEGER NOT NULL,
    PRIMARY KEY (origin_store_id, retraction_id, target_key)
);

CREATE TABLE IF NOT EXISTS origin_cursor (
    origin_store_id TEXT PRIMARY KEY,
    sequence_seen   INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS acknowledgements (
    retraction_id  TEXT    NOT NULL,
    recipient      TEXT    NOT NULL,
    state          TEXT    NOT NULL,
    state_revision INTEGER NOT NULL DEFAULT 0,
    detail         TEXT    NOT NULL DEFAULT '',
    at             TEXT    NOT NULL,
    PRIMARY KEY (retraction_id, recipient)
);
"""

MAX_ATTEMPTS = 8
BASE_BACKOFF_MS = 250


@dataclass(frozen=True)
class OutboxRow:
    id: int
    retraction_id: str
    recipient: str
    retraction: Retraction
    target_key: str
    state: PropagationState
    attempts: int
    next_attempt_ms: int
    last_error: str


class Outbox:
    """Durable delivery intent, sharing a connection with the event log.

    Every method takes the connection rather than opening its own, because the
    whole point is to be inside the caller's transaction.
    """

    def __init__(self, conn: Connection) -> None:
        self._conn = conn
        # NOT wrapped in `transaction()`: `executescript` issues its own
        # COMMIT before running, which would end ours and leave the
        # context manager committing a transaction that no longer exists.
        # Safe unwrapped because every statement is `IF NOT EXISTS` and,
        # with `isolation_level=None`, each autocommits.
        self._migrate_target_key("inbox")
        self._migrate_target_key("outbox")
        self._conn.executescript(_SCHEMA)

    def _migrate_target_key(self, table: str) -> None:
        """Widen a table's key to include the per-hop retraction target.

        Schema 0.3.0 keyed the inbox on `(origin_store_id, retraction_id)`.
        Transitive forwarding needs the target as well (see
        `Retraction.dedupe_key`), and a primary key cannot be widened in place
        in SQLite, so the table is rebuilt.

        Existing rows migrate with `target_key = ''`. That is correct rather
        than merely convenient: every row written under 0.3.0 was a hop-0
        retraction whose target *was* the origin, and leaving the key empty
        keeps those rows deduplicating exactly as they did. A re-delivery of
        one of them arrives with no target fields either, so it computes the
        same empty key and still matches.
        """
        tables = {
            row[0]
            for row in self._conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        if table not in tables:
            return  # fresh store: _SCHEMA creates it in the new shape
        columns = [row[1] for row in self._conn.execute(f"PRAGMA table_info({table})")]
        if "target_key" in columns:
            return
        old = f"{table}_pre_0_4_0"
        carried = ", ".join(columns)
        self._conn.execute(f"ALTER TABLE {table} RENAME TO {old}")
        # Indexes follow a rename, and would then collide with the ones
        # `_SCHEMA` recreates. Drop them before rebuilding.
        for (name,) in self._conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'index' AND tbl_name = ?"
            " AND name NOT LIKE 'sqlite_%'",
            (old,),
        ).fetchall():
            self._conn.execute(f"DROP INDEX IF EXISTS {name}")
        self._conn.executescript(_SCHEMA)
        self._conn.execute(
            f"INSERT INTO {table} ({carried}, target_key) "
            f"SELECT {carried}, '' FROM {old}"
        )
        self._conn.execute(f"DROP TABLE {old}")

    # --- origin side -----------------------------------------------------

    def enqueue(
        self,
        retraction: Retraction,
        recipients: Sequence[str],
        now_ms: int,
    ) -> int:
        """Record that a retraction is owed to each recipient.

        **Must be called inside the same transaction that appends the
        `RetractionRequested` event.** `MemoryFabric.request_retraction` does
        that; calling this alone is how invariant 3 gets broken again.

        Re-enqueuing the same `(retraction, recipient)` is a no-op rather than a
        duplicate row, so a retried request does not create two deliveries.
        """
        payload = json.dumps(retraction.to_json(), sort_keys=True)
        added = 0
        for recipient in recipients:
            cursor = self._conn.execute(
                "INSERT OR IGNORE INTO outbox "
                "(retraction_id, recipient, target_key, payload, state, "
                "next_attempt_ms, updated_ms) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    retraction.retraction_id,
                    recipient,
                    retraction.dedupe_key[2],
                    payload,
                    PropagationState.QUEUED.value,
                    now_ms,
                    now_ms,
                ),
            )
            added += cursor.rowcount or 0
        return added

    def due(self, now_ms: int, limit: int = 100) -> list[OutboxRow]:
        rows = self._conn.execute(
            "SELECT * FROM outbox WHERE state IN (?, ?) AND next_attempt_ms <= ? "
            "ORDER BY id LIMIT ?",
            (
                PropagationState.QUEUED.value,
                PropagationState.RETRYING.value,
                now_ms,
                limit,
            ),
        ).fetchall()
        return [self._row(row) for row in rows]

    def pending(self) -> list[OutboxRow]:
        """Everything still **owed**. This is what an operator needs: a
        permanent failure that vanished would be worse than one that keeps
        complaining.

        `SETTLED_STATES` rather than `TERMINAL_STATES`, because `enforced` is
        settled — nothing left to do — while still able to progress to
        `verified`. The two were one constant until a property test found
        `enforced` declaring an outgoing transition while being called
        terminal.
        """
        terminal = {state.value for state in SETTLED_STATES}
        rows = self._conn.execute("SELECT * FROM outbox ORDER BY id").fetchall()
        return [self._row(row) for row in rows if row["state"] not in terminal]

    def state_of(
        self,
        retraction_id: str,
        recipient: str,
        target_key: str | None = None,
    ) -> PropagationState:
        """The state of one delivery.

        With `target_key` None and several hop targets outstanding for the pair,
        the *least* advanced is returned, so a caller asking "is this settled?"
        is not told yes while a sibling target is still queued.
        """
        clause, params = _target_clause(target_key)
        rows = self._conn.execute(
            f"SELECT state FROM outbox WHERE retraction_id = ? AND recipient = ?{clause}",
            (retraction_id, recipient, *params),
        ).fetchall()
        if not rows:
            return PropagationState.UNKNOWN
        states = [PropagationState(row["state"]) for row in rows]
        return min(states, key=lambda state: _PROGRESS.index(state))

    def advance(
        self,
        retraction_id: str,
        recipient: str,
        target: PropagationState,
        now_ms: int,
        error: str = "",
        target_key: str | None = None,
    ) -> bool:
        """Move one pair through the state machine, refusing illegal moves.

        Returns False rather than raising when the transition is not allowed, so
        a duplicate acknowledgement arriving late cannot drag an `enforced` pair
        back to `persisted`.

        `target_key` left as None addresses every hop target for the pair, which
        is the whole row set whenever a campaign has one target — the only case
        that existed before transitive forwarding.
        """
        current = self.state_of(retraction_id, recipient, target_key)
        if current == target:
            return True
        if not can_transition(current, target):
            return False
        clause, params = _target_clause(target_key)
        self._conn.execute(
            "UPDATE outbox SET state = ?, last_error = ?, updated_ms = ? "
            f"WHERE retraction_id = ? AND recipient = ?{clause}",
            (target.value, error, now_ms, retraction_id, recipient, *params),
        )
        return True

    def record_attempt(
        self, row: OutboxRow, now_ms: int, error: str
    ) -> PropagationState:
        """A transient failure: back off, or give up visibly.

        Backoff is bounded exponential with jitter derived from the row id, so
        two recipients failing together do not retry in lockstep. Deterministic
        jitter, because a test has to be able to predict it.
        """
        attempts = row.attempts + 1
        if attempts >= MAX_ATTEMPTS:
            self._conn.execute(
                "UPDATE outbox SET state = ?, attempts = ?, last_attempt_ms = ?, "
                "last_error = ?, updated_ms = ? WHERE id = ?",
                (
                    PropagationState.FAILED.value,
                    attempts,
                    now_ms,
                    error,
                    now_ms,
                    row.id,
                ),
            )
            return PropagationState.FAILED

        jitter = (row.id * 37) % BASE_BACKOFF_MS
        delay = BASE_BACKOFF_MS * (2 ** (attempts - 1)) + jitter
        self._conn.execute(
            "UPDATE outbox SET state = ?, attempts = ?, last_attempt_ms = ?, "
            "next_attempt_ms = ?, last_error = ?, updated_ms = ? WHERE id = ?",
            (
                PropagationState.RETRYING.value,
                attempts,
                now_ms,
                now_ms + delay,
                error,
                now_ms,
                row.id,
            ),
        )
        return PropagationState.RETRYING

    def record_acknowledgement(self, ack: Acknowledgement) -> None:
        """Persist what a recipient claimed, at the origin.

        Held in memory it would be lost on a crash, and the origin would have no
        record of what had been confirmed.
        """
        self._conn.execute(
            "INSERT INTO acknowledgements (retraction_id, recipient, state, "
            "state_revision, detail, at) VALUES (?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(retraction_id, recipient) DO UPDATE SET "
            "state = excluded.state, state_revision = excluded.state_revision, "
            "detail = excluded.detail, at = excluded.at",
            (
                ack.retraction_id,
                ack.recipient_store_id,
                ack.state.value,
                ack.state_revision,
                ack.detail,
                ack.at,
            ),
        )

    def acknowledgements(self, retraction_id: str) -> dict[str, Acknowledgement]:
        rows = self._conn.execute(
            "SELECT * FROM acknowledgements WHERE retraction_id = ?", (retraction_id,)
        ).fetchall()
        return {
            row["recipient"]: Acknowledgement(
                retraction_id=row["retraction_id"],
                recipient_store_id=row["recipient"],
                state=PropagationState(row["state"]),
                at=row["at"],
                state_revision=row["state_revision"],
                detail=row["detail"],
            )
            for row in rows
        }

    # --- recipient side --------------------------------------------------

    def seen(self, retraction: Retraction) -> tuple[str, str] | None:
        """The first outcome for this `(origin, retraction_id, target)`, if any.

        A second copy returns the **first** outcome; it does not re-apply. That
        is deduplication by event identity, which — unlike skipping an
        already-quarantined memory — can distinguish a replay from a new
        retraction of the same memory.
        """
        row = self._conn.execute(
            "SELECT outcome, detail FROM inbox "
            "WHERE origin_store_id = ? AND retraction_id = ? AND target_key = ?",
            retraction.dedupe_key,
        ).fetchone()
        return (row["outcome"], row["detail"]) if row else None

    def record_inbox(
        self, retraction: Retraction, outcome: str, detail: str, now_ms: int
    ) -> None:
        """Must be in the same transaction as the lifecycle change it records."""
        self._conn.execute(
            "INSERT OR IGNORE INTO inbox (origin_store_id, retraction_id, "
            "target_key, origin_sequence, outcome, detail, received_ms) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                *retraction.dedupe_key,
                retraction.origin_sequence,
                outcome,
                detail,
                now_ms,
            ),
        )

    def max_inbox_sequence(self, origin_store_id: str, retraction_ids: set[str]) -> int | None:
        """The highest origin sequence among these retractions' inbox records."""
        best: int | None = None
        for retraction_id in retraction_ids:
            row = self._conn.execute(
                "SELECT MAX(origin_sequence) AS s FROM inbox WHERE origin_store_id = ? "
                "AND retraction_id = ?", (origin_store_id, retraction_id)).fetchone()
            if row is not None and row["s"] is not None:
                best = int(row["s"]) if best is None else max(best, int(row["s"]))
        return best

    def inbox_count(self, origin_store_id: str) -> int:
        """How many retractions from this origin this store has recorded."""
        row = self._conn.execute(
            "SELECT COUNT(*) AS n FROM inbox WHERE origin_store_id = ?", (origin_store_id,)
        ).fetchone()
        return int(row["n"]) if row is not None else 0

    def cursor_for(self, origin_store_id: str) -> int:
        row = self._conn.execute(
            "SELECT sequence_seen FROM origin_cursor WHERE origin_store_id = ?",
            (origin_store_id,),
        ).fetchone()
        return int(row["sequence_seen"]) if row else -1

    def advance_cursor(self, origin_store_id: str, sequence: int) -> None:
        """Monotonic per origin. `MAX` rather than assignment so a reordered
        delivery cannot rewind the cursor and re-open a window that was closed.
        """
        self._conn.execute(
            "INSERT INTO origin_cursor (origin_store_id, sequence_seen) VALUES (?, ?) "
            "ON CONFLICT(origin_store_id) DO UPDATE SET sequence_seen = "
            # A CASE rather than SQLite's two-argument MAX(), and the column
            # qualified: the same statement then means the same thing on
            # SQLite and Postgres (which spells MAX(a, b) as GREATEST and
            # rejects the unqualified name as ambiguous inside an upsert).
            "CASE WHEN excluded.sequence_seen > origin_cursor.sequence_seen "
            "THEN excluded.sequence_seen ELSE origin_cursor.sequence_seen END",
            (origin_store_id, sequence),
        )

    def missed_since(self, origin_store_id: str) -> int:
        """What a recipient tells an origin on reconnect, so the origin can
        replay everything above it. The cursor is the recipient's, never the
        origin's guess about it: replaying too much is safe because processing
        is idempotent, and replaying too little is the only real failure.

        A limit, stated: it is the highest sequence seen, so a retraction
        delayed past a later one sits below it and reconciliation will not ask
        for it again. Delivery does not depend on reconciliation -- the
        origin's outbox keeps retrying, and one that exhausts its retries shows
        as `failed` in `doctor` -- but a recipient cannot use this cursor to
        prove it missed nothing."""
        return self.cursor_for(origin_store_id)

    # --- plumbing --------------------------------------------------------

    def _row(self, row: Row) -> OutboxRow:
        return OutboxRow(
            id=row["id"],
            retraction_id=row["retraction_id"],
            recipient=row["recipient"],
            retraction=Retraction.from_json(json.loads(row["payload"])),
            target_key=row["target_key"] or "",
            state=PropagationState(row["state"]),
            attempts=row["attempts"],
            next_attempt_ms=row["next_attempt_ms"],
            last_error=row["last_error"] or "",
        )


def _target_clause(target_key: str | None) -> tuple[str, tuple[str, ...]]:
    """An optional `AND target_key = ?`, so one query serves both callers."""
    if target_key is None:
        return "", ()
    return " AND target_key = ?", (target_key,)


_PROGRESS = (
    PropagationState.UNKNOWN,
    PropagationState.REQUESTED,
    PropagationState.QUEUED,
    PropagationState.RETRYING,
    PropagationState.DELIVERED,
    PropagationState.PERSISTED,
    PropagationState.ENFORCED,
    PropagationState.VERIFIED,
    PropagationState.SUPERSEDED,
    PropagationState.REJECTED,
    PropagationState.FAILED,
)
"""How far along each state is, for `state_of` over several hop targets. Only
an ordering; the legal moves live in `ALLOWED_TRANSITIONS`."""


def now_ms() -> int:
    return int(time.time() * 1000)
