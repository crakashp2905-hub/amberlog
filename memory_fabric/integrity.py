"""A hash chain over the event log, and checkpoints anchored outside it.

## Why this exists

Twice in this repository a security property was justified by citing "the event
digests", and twice there were none. The `seal` docstring claimed the missing
authentication tag was covered by "the append-only log and the event digests";
the federation handler claimed an unauthenticated request was refused before
parsing. Both sentences were written before the mechanism they named.

The append-only triggers do real work — a tamper needs file write access to
drop `events_no_update` first, and `memory-fabric doctor` reports a missing
trigger. But a trigger is a *guard*, not evidence: once dropped, edited and
recreated, nothing in the log disagrees with the edit. Content ciphertext is
now authenticated (`governance/cipher.py`), which covers a memory's text. It
does not cover an event's `ts`, `type`, `agent_id`, `episode_id`, or the
payload of an event that carries no content at all — a `LifecycleChanged`, a
`RetractionApplied`, an `ExposureDecided`.

So: each appended event is hashed, and each hash is chained into its
predecessor. Editing or deleting any event breaks every link after it, and the
break names the first divergent sequence number.

## What a hash chain does and does not give

**Does:** detect any modification, deletion or reordering of events *within*
the chained range, and name where it starts.

**Does not:** stop someone who can write the file from recomputing the whole
chain. A chain is tamper-*evident*, not tamper-proof, and anyone with write
access to both the log and the chain can rewrite both consistently.

That is why `Checkpoint` exists and why it is meaningless until it leaves the
machine. A checkpoint is `(seq, digest)` — small enough to email, commit to
another repository, write to append-only object storage or read out over the
phone. An attacker who rewrites the chain cannot reach a digest you wrote down
elsewhere, so the forgery is detectable at the next comparison. Keeping the
checkpoint beside the database buys nothing, and `verify_against` says so
rather than implying otherwise.

## Coverage is explicit

Chaining starts when this table first appears, so a store written before it
has unchained events. `coverage()` reports the range, and verification is
honest about the gap rather than reporting "verified" for events nothing
covers. Backfilling would be worse than the gap: computing hashes now over
events nobody hashed then proves only that they are self-consistent today.
"""

from __future__ import annotations

from .dbtypes import Connection

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Iterator, Mapping

from .events import Event

_SCHEMA = """
CREATE TABLE IF NOT EXISTS integrity_chain (
    seq          INTEGER PRIMARY KEY,
    event_digest TEXT    NOT NULL,
    chain_digest TEXT    NOT NULL,
    recorded_ms  INTEGER NOT NULL
);

-- The chain is as append-only as the log it covers. Without these a tamper
-- could edit an event and update its link in one transaction, which is the
-- entire attack this module exists to detect.
CREATE TRIGGER IF NOT EXISTS integrity_chain_no_update
BEFORE UPDATE ON integrity_chain
BEGIN SELECT RAISE(ABORT, 'integrity chain is append-only'); END;

CREATE TRIGGER IF NOT EXISTS integrity_chain_no_delete
BEFORE DELETE ON integrity_chain
BEGIN SELECT RAISE(ABORT, 'integrity chain is append-only'); END;
"""

GENESIS = "0" * 64
"""The chain digest before anything is chained. A fixed value rather than an
empty string so a one-event chain still has a defined predecessor."""


@dataclass(frozen=True)
class Checkpoint:
    """A chain state small enough to store somewhere else.

    Worthless on the same disk as the log, which is the whole point: anyone who
    can rewrite the chain can rewrite a checkpoint sitting next to it. Written
    to another repository, append-only object storage, a ticket, or a sheet of
    paper, it becomes the thing a forged chain cannot reach.
    """

    seq: int
    chain_digest: str
    events: int

    def to_json(self) -> dict[str, Any]:
        return {
            "seq": self.seq,
            "chain_digest": self.chain_digest,
            "events": self.events,
        }

    @staticmethod
    def from_json(data: Mapping[str, Any]) -> "Checkpoint":
        return Checkpoint(
            seq=int(data["seq"]),
            chain_digest=str(data["chain_digest"]),
            events=int(data.get("events", 0)),
        )


@dataclass(frozen=True)
class Verification:
    """The result of recomputing the chain."""

    ok: bool
    checked: int
    first_bad_seq: int | None = None
    detail: str = ""
    covered_from: int | None = None
    covered_to: int | None = None
    unchained_before: int = 0
    """Events that predate the chain. Reported rather than ignored: a store
    that adopted chaining late has a genuine gap, and calling the whole log
    "verified" would be the same overstatement this module was built to end."""

    def to_json(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "checked": self.checked,
            "first_bad_seq": self.first_bad_seq,
            "detail": self.detail,
            "covered_from": self.covered_from,
            "covered_to": self.covered_to,
            "unchained_before": self.unchained_before,
        }


def event_digest(event: Event) -> str:
    """A canonical hash of one event.

    Every field that is part of the record, and `seq` among them — so moving an
    event to another position breaks its own digest and not merely the chain.

    Canonical JSON with sorted keys and no whitespace, because two encoders
    that disagree about key order would produce two digests for one event and
    the chain would fail on a store that had done nothing wrong.
    """
    material = json.dumps(
        {
            "seq": event.seq,
            "event_id": event.event_id,
            "ts": event.ts,
            "type": str(event.type),
            "agent_id": event.agent_id,
            "episode_id": event.episode_id,
            "schema_version": event.schema_version,
            "payload": event.payload,
        },
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(material).hexdigest()


def link(previous_chain_digest: str, digest: str) -> str:
    return hashlib.sha256(
        (previous_chain_digest + digest).encode("utf-8")
    ).hexdigest()


class IntegrityChain:
    """Hash-chains appended events, and verifies the chain afterwards.

    Shares the event log's connection so a link commits in the same transaction
    as the event it covers. Separately committed links would leave a window
    where an event exists unchained, and a crash in that window would be
    indistinguishable from a deletion.
    """

    def __init__(self, conn: Connection) -> None:
        self._conn = conn
        # Not inside `transaction()`: `executescript` issues its own COMMIT,
        # which would end ours. Safe unwrapped because every statement is
        # `IF NOT EXISTS`.
        self._conn.executescript(_SCHEMA)

    # --- writing ---------------------------------------------------------

    def head(self) -> tuple[int, str]:
        """The last chained sequence and its digest, or `(0, GENESIS)`."""
        row = self._conn.execute(
            "SELECT seq, chain_digest FROM integrity_chain ORDER BY seq DESC LIMIT 1"
        ).fetchone()
        if row is None:
            return (0, GENESIS)
        return (int(row["seq"]), str(row["chain_digest"]))

    def extend(self, events: list[Event], now_ms: int) -> str:
        """Chain these events. **Must run inside the appending transaction.**

        Returns the new head digest. Events are chained in `seq` order rather
        than call order, because the chain's meaning is the log's order and
        nothing else.
        """
        _, previous = self.head()
        for event in sorted(events, key=lambda e: e.seq or 0):
            if event.seq is None:  # pragma: no cover - append assigns it
                raise ValueError("cannot chain an event with no sequence")
            digest = event_digest(event)
            previous = link(previous, digest)
            self._conn.execute(
                "INSERT INTO integrity_chain (seq, event_digest, chain_digest, "
                "recorded_ms) VALUES (?, ?, ?, ?)",
                (event.seq, digest, previous, now_ms),
            )
        return previous

    # --- reading ---------------------------------------------------------

    def coverage(self) -> tuple[int | None, int | None]:
        row = self._conn.execute(
            "SELECT MIN(seq) AS lo, MAX(seq) AS hi FROM integrity_chain"
        ).fetchone()
        if row is None or row["lo"] is None:
            return (None, None)
        return (int(row["lo"]), int(row["hi"]))

    def digest_at(self, seq: int) -> str | None:
        """The chain digest recorded at `seq`, or None if it is not chained."""
        row = self._conn.execute(
            "SELECT chain_digest FROM integrity_chain WHERE seq = ?", (seq,)
        ).fetchone()
        return str(row["chain_digest"]) if row is not None else None

    def checkpoint(self) -> Checkpoint:
        seq, digest = self.head()
        return Checkpoint(seq=seq, chain_digest=digest, events=len(self))

    def __len__(self) -> int:
        row = self._conn.execute("SELECT count(*) FROM integrity_chain").fetchone()
        return int(row[0]) if row is not None else 0

    def verify(self, events: Iterator[Event]) -> Verification:
        """Recompute the chain over `events` and report the first divergence.

        Takes the events rather than reading them itself, so the caller decides
        whether it is verifying the live log, a backup, or a restored copy — and
        so this cannot accidentally verify a different log from the one the
        caller cares about.
        """
        rows = {
            int(row["seq"]): (str(row["event_digest"]), str(row["chain_digest"]))
            for row in self._conn.execute(
                "SELECT seq, event_digest, chain_digest FROM integrity_chain ORDER BY seq"
            )
        }
        low, high = self.coverage()
        if low is None or high is None:
            return Verification(
                ok=True, checked=0,
                detail="no chain recorded; nothing to verify and nothing claimed",
            )

        previous = GENESIS
        anchored = False
        checked = 0
        unchained = 0
        for event in events:
            if event.seq is None:
                continue
            if event.seq < low:
                unchained += 1
                continue
            if event.seq > high:
                # Events appended after the last link. Not a failure: the
                # caller may be verifying a backup taken before them.
                break
            recorded = rows.get(event.seq)
            if recorded is None:
                return Verification(
                    ok=False, checked=checked, first_bad_seq=event.seq,
                    detail=f"event {event.seq} is inside the chained range but has no link",
                    covered_from=low, covered_to=high, unchained_before=unchained,
                )
            expected_event_digest, expected_chain = recorded
            actual = event_digest(event)
            if actual != expected_event_digest:
                return Verification(
                    ok=False, checked=checked, first_bad_seq=event.seq,
                    detail=f"event {event.seq} does not match its recorded digest",
                    covered_from=low, covered_to=high, unchained_before=unchained,
                )
            if not anchored:
                anchored = True
                if unchained:
                    # The chain starts above the log's first event, so its
                    # first link was computed over history nobody hashed and
                    # cannot be re-derived. Anchor on the recorded digest and
                    # verify every link *after* it; `unchained_before` reports
                    # the size of what is therefore not covered.
                    #
                    # The alternative — recomputing from GENESIS over a partial
                    # range — reported a divergence at the first covered event
                    # on every late-adopting store, which is a false alarm and
                    # the worst kind: it would teach an operator to ignore the
                    # check.
                    previous = expected_chain
                    checked += 1
                    continue
            previous = link(previous, actual)
            if previous != expected_chain:
                return Verification(
                    ok=False, checked=checked, first_bad_seq=event.seq,
                    detail=(
                        f"the chain diverges at event {event.seq}: a link was "
                        "recomputed or an earlier event was removed"
                    ),
                    covered_from=low, covered_to=high, unchained_before=unchained,
                )
            checked += 1

        missing = len(rows) - checked
        if missing > 0:
            return Verification(
                ok=False, checked=checked, first_bad_seq=None,
                detail=f"{missing} chained event(s) are no longer in the log",
                covered_from=low, covered_to=high, unchained_before=unchained,
            )
        return Verification(
            ok=True, checked=checked,
            detail=f"{checked} event(s) verified",
            covered_from=low, covered_to=high, unchained_before=unchained,
        )

    def verify_against(self, checkpoint: Checkpoint) -> Verification:
        """Compare the live chain with a checkpoint taken earlier.

        This is the check that survives an attacker who can write the file,
        **and only if the checkpoint came from somewhere else.** A checkpoint
        read back from the same database proves nothing, because whoever
        rewrote the chain could rewrite that too.
        """
        row = self._conn.execute(
            "SELECT chain_digest FROM integrity_chain WHERE seq = ?",
            (checkpoint.seq,),
        ).fetchone()
        if row is None:
            return Verification(
                ok=False, checked=0, first_bad_seq=checkpoint.seq,
                detail=(
                    f"the chain has no link at sequence {checkpoint.seq}; the log "
                    "has been truncated or replaced"
                ),
            )
        if str(row["chain_digest"]) != checkpoint.chain_digest:
            return Verification(
                ok=False, checked=0, first_bad_seq=checkpoint.seq,
                detail=(
                    f"the chain digest at sequence {checkpoint.seq} does not match "
                    "the checkpoint; history before this point has been altered"
                ),
            )
        return Verification(
            ok=True, checked=1,
            detail=f"the chain matches the checkpoint at sequence {checkpoint.seq}",
        )
