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

import json
import sqlite3
import time
from dataclasses import dataclass
from typing import Iterable, Sequence

from .protocol import (
    Acknowledgement,
    PropagationState,
    Retraction,
    TERMINAL_STATES,
    can_transition,
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS outbox (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    retraction_id   TEXT    NOT NULL,
    recipient       TEXT    NOT NULL,
    payload         TEXT    NOT NULL,
    state           TEXT    NOT NULL,
    attempts        INTEGER NOT NULL DEFAULT 0,
    last_attempt_ms INTEGER,
    next_attempt_ms INTEGER NOT NULL DEFAULT 0,
    last_error      TEXT,
    updated_ms      INTEGER NOT NULL,
    UNIQUE (retraction_id, recipient)
);
CREATE INDEX IF NOT EXISTS outbox_due ON outbox (state, next_attempt_ms);

CREATE TABLE IF NOT EXISTS inbox (
    origin_store_id TEXT    NOT NULL,
    retraction_id   TEXT    NOT NULL,
    origin_sequence INTEGER NOT NULL,
    outcome         TEXT    NOT NULL,
    detail          TEXT    NOT NULL DEFAULT '',
    received_ms     INTEGER NOT NULL,
    PRIMARY KEY (origin_store_id, retraction_id)
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
    state: PropagationState
    attempts: int
    next_attempt_ms: int
    last_error: str


class Outbox:
    """Durable delivery intent, sharing a connection with the event log.

    Every method takes the connection rather than opening its own, because the
    whole point is to be inside the caller's transaction.
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn
        with self._conn:
            self._conn.executescript(_SCHEMA)

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
                "(retraction_id, recipient, payload, state, next_attempt_ms, updated_ms) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    retraction.retraction_id,
                    recipient,
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
        """Everything not in a terminal state. This is what an operator needs:
        a permanent failure that vanished would be worse than one that keeps
        complaining."""
        terminal = {state.value for state in TERMINAL_STATES}
        rows = self._conn.execute("SELECT * FROM outbox ORDER BY id").fetchall()
        return [self._row(row) for row in rows if row["state"] not in terminal]

    def state_of(self, retraction_id: str, recipient: str) -> PropagationState:
        row = self._conn.execute(
            "SELECT state FROM outbox WHERE retraction_id = ? AND recipient = ?",
            (retraction_id, recipient),
        ).fetchone()
        return PropagationState(row["state"]) if row else PropagationState.UNKNOWN

    def advance(
        self,
        retraction_id: str,
        recipient: str,
        target: PropagationState,
        now_ms: int,
        error: str = "",
    ) -> bool:
        """Move one pair through the state machine, refusing illegal moves.

        Returns False rather than raising when the transition is not allowed, so
        a duplicate acknowledgement arriving late cannot drag an `enforced` pair
        back to `persisted`.
        """
        current = self.state_of(retraction_id, recipient)
        if current == target:
            return True
        if not can_transition(current, target):
            return False
        self._conn.execute(
            "UPDATE outbox SET state = ?, last_error = ?, updated_ms = ? "
            "WHERE retraction_id = ? AND recipient = ?",
            (target.value, error, now_ms, retraction_id, recipient),
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
        """The first outcome for this `(origin, retraction_id)`, if any.

        A second copy returns the **first** outcome; it does not re-apply. That
        is deduplication by event identity, which — unlike skipping an
        already-quarantined memory — can distinguish a replay from a new
        retraction of the same memory.
        """
        row = self._conn.execute(
            "SELECT outcome, detail FROM inbox WHERE origin_store_id = ? AND retraction_id = ?",
            retraction.dedupe_key,
        ).fetchone()
        return (row["outcome"], row["detail"]) if row else None

    def record_inbox(
        self, retraction: Retraction, outcome: str, detail: str, now_ms: int
    ) -> None:
        """Must be in the same transaction as the lifecycle change it records."""
        self._conn.execute(
            "INSERT OR IGNORE INTO inbox (origin_store_id, retraction_id, "
            "origin_sequence, outcome, detail, received_ms) VALUES (?, ?, ?, ?, ?, ?)",
            (
                retraction.origin_store_id,
                retraction.retraction_id,
                retraction.origin_sequence,
                outcome,
                detail,
                now_ms,
            ),
        )

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
            "ON CONFLICT(origin_store_id) DO UPDATE SET "
            "sequence_seen = MAX(sequence_seen, excluded.sequence_seen)",
            (origin_store_id, sequence),
        )

    def missed_since(self, origin_store_id: str) -> int:
        """What a recipient tells an origin on reconnect, so the origin can
        replay everything above it. The cursor is the recipient's, never the
        origin's guess about it: replaying too much is safe because processing
        is idempotent, and replaying too little is the only real failure."""
        return self.cursor_for(origin_store_id)

    # --- plumbing --------------------------------------------------------

    def _row(self, row: sqlite3.Row) -> OutboxRow:
        return OutboxRow(
            id=row["id"],
            retraction_id=row["retraction_id"],
            recipient=row["recipient"],
            retraction=Retraction.from_json(json.loads(row["payload"])),
            state=PropagationState(row["state"]),
            attempts=row["attempts"],
            next_attempt_ms=row["next_attempt_ms"],
            last_error=row["last_error"] or "",
        )


def now_ms() -> int:
    return int(time.time() * 1000)
