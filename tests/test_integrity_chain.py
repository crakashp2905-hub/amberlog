"""The hash chain, and whether it actually detects a tamper.

Twice in this repository a security property was justified by citing "the event
digests", and twice there were none. So these tests are mostly attacks: edit an
event, delete one, reorder two, recompute the chain, truncate the log. Each must
be caught, and caught at the right sequence number, because "something is
wrong somewhere" is not a useful audit answer.

The last group is the honest part. A hash chain is tamper-*evident*, not
tamper-proof: anyone who can write both the log and the chain can rewrite both
consistently. The only defence against that is a checkpoint kept somewhere
else, and `verify_against` is tested for exactly the case where it works and
the case where it cannot.
"""

from __future__ import annotations

import json
import sqlite3
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from amberlog import Amberlog
from amberlog.eventlog import EventLog
from amberlog.events import Event
from amberlog.integrity import (
    GENESIS,
    Checkpoint,
    IntegrityChain,
    event_digest,
    link,
)


class ChainCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = Path(self._tmp.name) / "store.db"
        fabric = Amberlog(self.path, auto_activate=True, encrypt_content=False)
        try:
            for index in range(5):
                fabric.remember(agent_id="ag", content=f"observation {index}")
            self.checkpoint = fabric.log.chain.checkpoint()
        finally:
            fabric.close()

    def reopen(self) -> Amberlog:
        fabric = Amberlog(self.path, auto_activate=True, encrypt_content=False)
        self.addCleanup(fabric.close)
        return fabric

    def tamper(self, statements: list[tuple[str, tuple]]) -> None:
        """Edit the database behind the triggers, as someone with the file would."""
        conn = sqlite3.connect(self.path)
        try:
            with conn:
                conn.execute("DROP TRIGGER events_no_update")
                conn.execute("DROP TRIGGER events_no_delete")
                for sql, params in statements:
                    conn.execute(sql, params)
                conn.execute(
                    "CREATE TRIGGER events_no_update BEFORE UPDATE ON events "
                    "BEGIN SELECT RAISE(ABORT, 'append-only'); END"
                )
                conn.execute(
                    "CREATE TRIGGER events_no_delete BEFORE DELETE ON events "
                    "BEGIN SELECT RAISE(ABORT, 'append-only'); END"
                )
        finally:
            conn.close()


class TheHappyPath(ChainCase):
    def test_an_untouched_log_verifies(self) -> None:
        fabric = self.reopen()
        result = fabric.log.chain.verify(fabric.log.read())
        self.assertTrue(result.ok, result.detail)
        self.assertGreater(result.checked, 0)
        self.assertEqual(result.unchained_before, 0)

    def test_every_event_is_chained(self) -> None:
        fabric = self.reopen()
        self.assertEqual(len(fabric.log.chain), len(fabric.log))

    def test_the_chain_is_itself_append_only(self) -> None:
        """Without this a tamper could edit an event and fix its link in one
        transaction, which is the entire attack this module detects."""
        fabric = self.reopen()
        for sql in (
            "UPDATE integrity_chain SET chain_digest = 'x' WHERE seq = 2",
            "DELETE FROM integrity_chain WHERE seq = 2",
        ):
            with self.subTest(sql.split()[0]):
                with self.assertRaises(sqlite3.DatabaseError):
                    fabric.log._conn.execute(sql)

    def test_appending_extends_the_chain(self) -> None:
        fabric = self.reopen()
        before = fabric.log.chain.checkpoint()
        fabric.remember(agent_id="ag", content="one more")
        after = fabric.log.chain.checkpoint()
        self.assertGreater(after.seq, before.seq)
        self.assertNotEqual(after.chain_digest, before.chain_digest)
        self.assertTrue(fabric.log.chain.verify(fabric.log.read()).ok)


class ItDetectsTampering(ChainCase):
    def test_an_edited_payload_is_caught(self) -> None:
        """The case content encryption does not cover: an event's own fields."""
        fabric = self.reopen()
        seq, payload = fabric.log._conn.execute(
            "SELECT seq, payload FROM events WHERE type = 'MemoryCreated' LIMIT 1"
        ).fetchone()
        document = json.loads(payload)
        document["memory"]["content"] = "something else entirely"
        fabric.close()

        self.tamper([("UPDATE events SET payload = ? WHERE seq = ?",
                      (json.dumps(document), seq))])

        fabric = self.reopen()
        result = fabric.log.chain.verify(fabric.log.read())
        self.assertFalse(result.ok)
        self.assertEqual(result.first_bad_seq, seq)
        self.assertIn("digest", result.detail)

    def test_an_edited_timestamp_is_caught(self) -> None:
        """No content involved at all, so nothing else in the system would
        notice."""
        self.tamper([("UPDATE events SET ts = ts + 86400 WHERE seq = 3", ())])
        result = self.reopen().log.chain.verify(self.reopen().log.read())
        self.assertFalse(result.ok)
        self.assertEqual(result.first_bad_seq, 3)

    def test_an_edited_actor_is_caught(self) -> None:
        """Reattributing an action is a tamper with no effect on any memory."""
        self.tamper([("UPDATE events SET agent_id = 'someone-else' WHERE seq = 2", ())])
        result = self.reopen().log.chain.verify(self.reopen().log.read())
        self.assertFalse(result.ok)
        self.assertEqual(result.first_bad_seq, 2)

    def test_a_deleted_event_is_caught(self) -> None:
        self.tamper([("DELETE FROM events WHERE seq = 3", ())])
        fabric = self.reopen()
        result = fabric.log.chain.verify(fabric.log.read())
        self.assertFalse(result.ok)
        # Caught at the first event *after* the hole, because that link was
        # computed over a predecessor that is now missing.
        self.assertEqual(result.first_bad_seq, 4)

    def test_reordering_two_events_is_caught(self) -> None:
        """`seq` is inside each event's own digest, so moving an event breaks
        its digest and not merely its link."""
        conn = sqlite3.connect(self.path)
        try:
            rows = conn.execute(
                "SELECT seq, payload FROM events WHERE seq IN (3, 4) ORDER BY seq"
            ).fetchall()
        finally:
            conn.close()
        (_, third), (_, fourth) = rows
        self.tamper([
            ("UPDATE events SET payload = ? WHERE seq = 3", (fourth,)),
            ("UPDATE events SET payload = ? WHERE seq = 4", (third,)),
        ])
        result = self.reopen().log.chain.verify(self.reopen().log.read())
        self.assertFalse(result.ok)
        self.assertEqual(result.first_bad_seq, 3)

    def test_an_event_inside_the_range_with_no_link_is_caught(self) -> None:
        """A missing link in the middle is a failure, not a coverage gap.

        Distinct from a chain adopted late: there the gap is a prefix and is
        reported as `unchained_before`. A hole in the covered range means a
        link was removed.
        """
        conn = sqlite3.connect(self.path)
        try:
            with conn:
                conn.execute("DROP TRIGGER integrity_chain_no_delete")
                conn.execute("DELETE FROM integrity_chain WHERE seq = 3")
        finally:
            conn.close()
        fabric = self.reopen()
        result = fabric.log.chain.verify(fabric.log.read())
        self.assertFalse(result.ok)
        self.assertEqual(result.first_bad_seq, 3)
        self.assertIn("no link", result.detail)


class CoverageIsExplicit(ChainCase):
    def test_an_unchained_store_claims_nothing(self) -> None:
        """A store from before chaining existed. "Verified" for events nothing
        covers would be the same overstatement this module ended."""
        conn = sqlite3.connect(self.path)
        try:
            with conn:
                conn.execute("DROP TRIGGER integrity_chain_no_delete")
                conn.execute("DELETE FROM integrity_chain")
        finally:
            conn.close()
        fabric = self.reopen()
        result = fabric.log.chain.verify(fabric.log.read())
        self.assertTrue(result.ok)
        self.assertEqual(result.checked, 0)
        self.assertIn("nothing claimed", result.detail)

    def test_events_before_the_chain_are_counted_not_verified(self) -> None:
        """Adopting the chain late leaves a real gap, and the report names its
        size rather than hiding it."""
        conn = sqlite3.connect(self.path)
        try:
            with conn:
                conn.execute("DROP TRIGGER integrity_chain_no_delete")
                conn.execute("DELETE FROM integrity_chain WHERE seq <= 3")
        finally:
            conn.close()
        fabric = self.reopen()
        result = fabric.log.chain.verify(fabric.log.read())
        self.assertTrue(result.ok, result.detail)
        self.assertEqual(result.unchained_before, 3)
        self.assertEqual(result.covered_from, 4)


class CheckpointsAreTheRealDefence(ChainCase):
    def test_a_matching_checkpoint_verifies(self) -> None:
        fabric = self.reopen()
        self.assertTrue(fabric.log.chain.verify_against(self.checkpoint).ok)

    def test_a_recomputed_chain_is_caught_by_a_checkpoint(self) -> None:
        """The attack a chain alone cannot stop.

        Someone with write access edits an event *and* recomputes every link,
        so the chain is internally consistent and `verify` passes. Only a
        digest recorded elsewhere disagrees — which is why a checkpoint kept
        beside the database buys nothing.
        """
        conn = sqlite3.connect(self.path)
        try:
            with conn:
                conn.execute("DROP TRIGGER events_no_update")
                conn.execute("DROP TRIGGER integrity_chain_no_update")
                conn.execute("DROP TRIGGER integrity_chain_no_delete")
                conn.execute(
                    "UPDATE events SET agent_id = 'someone-else' WHERE seq = 2"
                )
                conn.execute("DELETE FROM integrity_chain")
        finally:
            conn.close()

        # Rebuild the chain over the altered log, exactly as an attacker would.
        log = EventLog(self.path)
        try:
            events = list(log.read())
            previous = GENESIS
            with log.transaction():
                for event in events:
                    digest = event_digest(event)
                    previous = link(previous, digest)
                    log._conn.execute(
                        "INSERT INTO integrity_chain (seq, event_digest, "
                        "chain_digest, recorded_ms) VALUES (?, ?, ?, ?)",
                        (event.seq, digest, previous, 0),
                    )
            # The forged chain is self-consistent: `verify` cannot tell.
            self.assertTrue(log.chain.verify(log.read()).ok)
            # The checkpoint taken before the tamper can.
            against = log.chain.verify_against(self.checkpoint)
            self.assertFalse(against.ok)
            self.assertIn("altered", against.detail)
        finally:
            log.close()

    def test_a_truncated_log_is_caught_by_a_checkpoint(self) -> None:
        conn = sqlite3.connect(self.path)
        try:
            with conn:
                conn.execute("DROP TRIGGER events_no_delete")
                conn.execute("DROP TRIGGER integrity_chain_no_delete")
                conn.execute("DELETE FROM events WHERE seq >= 4")
                conn.execute("DELETE FROM integrity_chain WHERE seq >= 4")
        finally:
            conn.close()
        fabric = self.reopen()
        result = fabric.log.chain.verify_against(self.checkpoint)
        self.assertFalse(result.ok)
        self.assertIn("truncated", result.detail)

    def test_a_checkpoint_round_trips_through_json(self) -> None:
        """It has to leave the machine to be worth anything, so it has to
        serialise."""
        restored = Checkpoint.from_json(
            json.loads(json.dumps(self.checkpoint.to_json()))
        )
        self.assertEqual(restored, self.checkpoint)


class TheDigestIsStable(unittest.TestCase):
    def test_key_order_does_not_change_the_digest(self) -> None:
        """Two encoders disagreeing about key order would give one event two
        digests, and the chain would fail on a store that had done nothing
        wrong."""
        # `event_id` pinned: it defaults to a fresh ULID, so two otherwise
        # identical events differ by construction.
        first = Event(type="T", ts=1, payload={"a": 1, "b": 2}, event_id="e", seq=1)
        second = Event(type="T", ts=1, payload={"b": 2, "a": 1}, event_id="e", seq=1)
        self.assertEqual(event_digest(first), event_digest(second))

    def test_the_sequence_is_part_of_the_digest(self) -> None:
        base = Event(type="T", ts=1, payload={"a": 1}, event_id="e", seq=1)
        moved = Event(type="T", ts=1, payload={"a": 1}, event_id="e", seq=2)
        self.assertNotEqual(event_digest(base), event_digest(moved))

    def test_every_recorded_field_is_covered(self) -> None:
        base = Event(
            type="T", ts=1, payload={"a": 1}, agent_id="x", episode_id="e",
            event_id="id", seq=1,
        )
        from dataclasses import replace

        for field, value in (
            ("type", "U"), ("ts", 2), ("agent_id", "y"), ("episode_id", "f"),
            ("event_id", "other"), ("schema_version", "9.9.9"),
            ("payload", {"a": 2}),
        ):
            with self.subTest(field):
                self.assertNotEqual(
                    event_digest(base), event_digest(replace(base, **{field: value}))
                )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
