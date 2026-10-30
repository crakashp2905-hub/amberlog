"""Transactions that nest, and the invariant that depended on them.

`sqlite3.Connection.__exit__` commits unconditionally and knows nothing about
nesting, so an inner `with conn:` inside an outer one commits the outer
transaction too. Every write in this project goes through
`EventLog.append_many`, which had exactly that — so
`MemoryFabric.request_retraction`, whose whole purpose is to commit a
quarantine, a `RetractionRequested` event and the outbox rows **together**,
was in fact three separate commits.

That is the half-state invariant 3 exists to prevent: a memory withdrawn
locally with nothing recording that any recipient is owed a correction. It was
claimed in INVARIANTS.md row 3, in `docs/PROTOCOL.md`, and in the Phase 1
commit message, and it was not true.

Nothing caught it for two reasons worth keeping in mind:

* the deterministic fault matrix simulates a crash by closing a handle, and a clean close commits everything anyway, so the half-state could never appear;
* no test made an *inner* step fail, so the rollback path was never exercised at all.

Both are covered here.
"""

from __future__ import annotations

import sqlite3
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from memory_fabric import LifecycleState, MemoryFabric
from memory_fabric.eventlog import EventLog
from memory_fabric.governance.firewall import (
    Firewall,
    rule_capabilities_must_be_granted,
    rule_must_be_active,
    rule_restricted_stays_private,
)
from memory_fabric.txn import depth, transaction


def permissive() -> Firewall:
    return Firewall(
        rules=[
            rule_must_be_active,
            rule_restricted_stays_private,
            rule_capabilities_must_be_granted,
        ]
    )


class NestingSemantics(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.log = EventLog(Path(self._tmp.name) / "log.db")
        self.addCleanup(self.log.close)

    def test_an_inner_level_does_not_commit_the_outer_one(self) -> None:
        """The actual defect, at the level it lives at."""
        with self.log.transaction():
            self.log.append(_event("A"))
            with self.log.transaction():
                self.log.append(_event("B"))
            # Still inside the outer transaction: an independent connection
            # must see nothing.
            self.assertEqual(self._rows_from_another_connection(), 0)
        self.assertEqual(self._rows_from_another_connection(), 2)

    def test_an_outer_rollback_discards_inner_work(self) -> None:
        with self.assertRaises(RuntimeError):
            with self.log.transaction():
                self.log.append(_event("A"))
                with self.log.transaction():
                    self.log.append(_event("B"))
                raise RuntimeError("the outer step failed")
        self.assertEqual(self._rows_from_another_connection(), 0)

    def test_an_inner_rollback_unwinds_only_to_its_savepoint(self) -> None:
        """A savepoint rather than a full rollback, so an outer caller can
        catch a nested failure and still decide to proceed."""
        with self.log.transaction():
            self.log.append(_event("kept"))
            try:
                with self.log.transaction():
                    self.log.append(_event("discarded"))
                    raise RuntimeError("the inner step failed")
            except RuntimeError:
                pass
            self.log.append(_event("also kept"))
        types = [event.type for event in self.log.read()]
        self.assertIn("kept", types)
        self.assertIn("also kept", types)
        self.assertNotIn("discarded", types)

    def test_the_depth_returns_to_zero(self) -> None:
        connection = self.log._conn
        self.assertEqual(depth(connection), 0)
        with self.log.transaction():
            self.assertEqual(depth(connection), 1)
            with self.log.transaction():
                self.assertEqual(depth(connection), 2)
            self.assertEqual(depth(connection), 1)
        self.assertEqual(depth(connection), 0)

    def test_the_depth_returns_to_zero_after_a_failure(self) -> None:
        """A leaked depth would start the next transaction at a non-zero level,
        and its final COMMIT would never run."""
        connection = self.log._conn
        with self.assertRaises(RuntimeError):
            with self.log.transaction():
                raise RuntimeError("boom")
        self.assertEqual(depth(connection), 0)
        # And the log is still usable.
        with self.log.transaction():
            self.log.append(_event("after"))
        self.assertEqual([e.type for e in self.log.read()], ["after"])

    def test_closing_forgets_the_depth(self) -> None:
        """Entries are keyed by `id(conn)` because a `sqlite3.Connection`
        cannot be weak-referenced — and an id is reused, so a stale entry would
        start a fresh log mid-transaction."""
        connection = self.log._conn
        with self.log.transaction():
            pass
        self.log.close()
        self.assertEqual(depth(connection), 0)

    def test_the_sibling_components_share_the_depth(self) -> None:
        """`EventLog`, `Outbox` and `ContentVault` share one connection
        precisely to share one transactional boundary. A per-object counter
        would have each opening nested transactions unaware of the others,
        which is the original bug with more steps.
        """
        connection = self.log._conn
        with self.log.transaction():
            self.assertEqual(depth(connection), 1)
            with transaction(connection):  # as the outbox does
                self.assertEqual(depth(connection), 2)

    def _rows_from_another_connection(self) -> int:
        other = sqlite3.connect(self.log.path)
        try:
            return other.execute("SELECT count(*) FROM events").fetchone()[0]
        finally:
            other.close()


class RequestRetractionIsAtomic(unittest.TestCase):
    """The invariant that was claimed and not held."""

    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = Path(self._tmp.name) / "store.db"
        fabric = MemoryFabric(self.path, firewall=permissive(), auto_activate=True)
        self.memory_id = fabric.remember(
            agent_id="ag", content="valve 7 is upstream of the pump"
        )
        fabric.close()

    def _open(self) -> MemoryFabric:
        fabric = MemoryFabric(self.path, firewall=permissive(), auto_activate=True)
        self.addCleanup(fabric.close)
        return fabric

    def test_a_failure_enqueuing_the_outbox_rolls_back_the_quarantine(self) -> None:
        """Before the fix: quarantined, event committed, nothing owed.

        The worst available outcome — the memory is gone from every agent's
        view and no recipient will ever be told, with the audit trail saying a
        retraction was requested.
        """
        fabric = self._open()

        def boom(*args: object, **kwargs: object) -> None:
            raise RuntimeError("simulated failure enqueuing the outbox rows")

        fabric.outbox.enqueue = boom  # type: ignore[assignment]
        with self.assertRaises(RuntimeError):
            fabric.request_retraction(
                self.memory_id, reason="contradicted",
                recipients=["st_somewhere"], basis="contradicted",
            )

        self.assertIs(
            fabric.get(self.memory_id).lifecycle_state, LifecycleState.ACTIVE
        )
        self.assertEqual(fabric.retractions_since(-1), [])
        self.assertEqual(fabric.outbox.pending(), [])

    def test_the_rollback_survives_a_reopen(self) -> None:
        """In-memory projections could be consistent while the disk is not;
        the log is the source of truth, so the reopen is the real assertion."""
        fabric = self._open()

        def boom(*args: object, **kwargs: object) -> None:
            raise RuntimeError("simulated failure")

        fabric.outbox.enqueue = boom  # type: ignore[assignment]
        with self.assertRaises(RuntimeError):
            fabric.request_retraction(
                self.memory_id, reason="contradicted",
                recipients=["st_somewhere"], basis="contradicted",
            )
        fabric.close()

        reopened = self._open()
        self.assertIs(
            reopened.get(self.memory_id).lifecycle_state, LifecycleState.ACTIVE
        )
        self.assertEqual(reopened.retractions_since(-1), [])
        self.assertEqual(reopened.outbox.pending(), [])

    def test_the_successful_path_commits_all_three_together(self) -> None:
        fabric = self._open()
        fabric.request_retraction(
            self.memory_id, reason="contradicted",
            recipients=["st_somewhere"], basis="contradicted",
        )
        fabric.close()

        reopened = self._open()
        self.assertIs(
            reopened.get(self.memory_id).lifecycle_state, LifecycleState.QUARANTINED
        )
        self.assertEqual(len(reopened.retractions_since(-1)), 1)
        self.assertEqual(
            [row.recipient for row in reopened.outbox.pending()], ["st_somewhere"]
        )

    def test_a_failure_applying_a_received_retraction_rolls_back(self) -> None:
        """The recipient side of the same guarantee.

        Phase D commits the local withdrawal and the onward obligation
        together; if recording the inbox row fails, the withdrawal must go with
        it rather than leaving a store that has forgotten it was told.
        """
        from memory_fabric.federation import offer

        other = MemoryFabric(
            Path(self._tmp.name) / "other.db", firewall=permissive(), auto_activate=True
        )
        self.addCleanup(other.close)
        origin = self._open()
        imported = offer(origin, self.memory_id, other, "ag-b", activate=True)
        self.assertTrue(imported.accepted, imported.reasons)

        retraction = origin.request_retraction(
            self.memory_id, reason="contradicted",
            recipients=[other.store_id], basis="contradicted",
        )

        def boom(*args: object, **kwargs: object) -> None:
            raise RuntimeError("simulated failure recording the inbox row")

        other.outbox.record_inbox = boom  # type: ignore[assignment]
        with self.assertRaises(RuntimeError):
            other.receive_retraction(retraction)

        self.assertIs(
            other.get(imported.imported_memory_id).lifecycle_state,
            LifecycleState.ACTIVE,
            "the withdrawal must not survive without the record of it",
        )


def _event(type_name: str):
    from memory_fabric.events import Event

    return Event(type=type_name, ts=0, payload={})



class RolledBackWritesLeaveNoIndexEntry(unittest.TestCase):
    """A write rolled back with its transaction must not stay in the copy index.

    It did: the replay after a rollback re-indexed what the log held but never
    unindexed what it no longer held, so the next similar write "recognised"
    a copy of a memory that did not exist and failed with a KeyError. Found
    by concurrent branch commits (tests/test_branching.py).
    """

    def test_a_similar_write_after_a_rollback_succeeds(self) -> None:
        f = MemoryFabric(":memory:", auto_activate=True)
        try:
            with self.assertRaises(RuntimeError):
                with f._transaction():
                    f.remember("a", "Pump P1 checked at 4 bar on the night shift.")
                    raise RuntimeError("roll back")
            mid = f.remember("a", "Pump P1 checked at 4 bar on the night shift, again.")
            self.assertIn(mid, f.state.memories)
            self.assertEqual(len(f.state.memories), 1)
        finally:
            f.close()


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
