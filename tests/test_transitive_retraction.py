"""Phase D — retraction across more than one hop.

Phase B measured retraction propagation and drove acting-on-withdrawn-knowledge
to 0%, but it measured a federation one hop deep: every recipient had imported
straight from the origin, so the origin's own recipient list named every store
holding a copy. The moment a recipient *re-shares*, that stops being true. The
origin does not know store C exists, and under the Phase B code there was
nothing anywhere that did — `offer` recorded the recipient agent and not the
recipient store, so no store could answer "who did I pass this to?".

These tests are about the cases that go wrong once the graph is deeper than
one hop, and most of them are about termination and double-counting rather than
about the happy path:

* a two-hop chain (the thing that silently failed before);
* a **diamond**, which is where the old deduplication key was actively unsafe;
* a **cycle**, which must terminate without the hop limit being what stops it;
* the hop limit, which must record a rejection rather than drop a retraction;
* forwarding intent committing with the local withdrawal, not after it;
* an unrelated memory downstream surviving — the whole project's question.
"""

from __future__ import annotations

import unittest
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory

from memory_fabric import LifecycleState, MemoryFabric
from memory_fabric.federation import offer
from memory_fabric.dispatcher import Dispatcher
from memory_fabric.events import EventType
from memory_fabric.model import MemoryType, ProvenanceMethod
from memory_fabric.outbox import now_ms
from memory_fabric.governance.firewall import (
    Firewall,
    rule_capabilities_must_be_granted,
    rule_must_be_active,
    rule_restricted_stays_private,
)
from memory_fabric.protocol import MAX_HOPS, PropagationState, RejectionCode


def permissive() -> Firewall:
    """The default firewall minus the value gate.

    Phase B measured that gate down to 42 imports of a possible 630, scoring
    identically to no federation at all, so a propagation test that left it on
    would mostly be measuring the gate.
    """
    return Firewall(
        rules=[
            rule_must_be_active,
            rule_restricted_stays_private,
            rule_capabilities_must_be_granted,
        ]
    )


class TransitiveRetractionTests(unittest.TestCase):
    """A chain A → B → C, built with the real `offer` path."""

    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        self.stores: dict[str, MemoryFabric] = {}
        self._reopened: list[MemoryFabric] = []
        self.a = self._store("a")
        self.b = self._store("b")
        self.c = self._store("c")

    def tearDown(self) -> None:
        # Explicit, because an open SQLite handle keeps a Windows file locked
        # and the cleanup then fails rather than the test.
        for store in (*self.stores.values(), *self._reopened):
            store.close()
        self.stores.clear()
        self._reopened.clear()
        self._tmp.cleanup()

    def _reopen(self, name: str) -> MemoryFabric:
        """A fresh handle on an existing store: how a crash is simulated.

        Registered for teardown under a distinct key, because the point is that
        two handles exist and the original must not be dropped from the
        transport while the test is still running.
        """
        fabric = MemoryFabric(self.dir / f"{name}.db", firewall=permissive())
        self._reopened.append(fabric)
        return fabric

    def _store(self, name: str) -> MemoryFabric:
        fabric = MemoryFabric(self.dir / f"{name}.db", firewall=permissive())
        self.stores[fabric.store_id] = fabric
        return fabric

    def _transport(self):
        from memory_fabric.transport import InProcessTransport

        return InProcessTransport(self.stores)

    def _drain(self, *, passes: int = 4) -> None:
        """Drain every store repeatedly.

        Repeatedly because forwarding is *asynchronous by construction*: B
        commits what it owes C and returns, so C's copy is still live until B's
        own dispatcher runs. That is the design — a synchronous cascade would
        put an unbounded number of network calls inside one recipient's
        transaction — and it means "retraction has converged" is a property of
        the system at rest, not of a single call.
        """
        transport = self._transport()
        for _ in range(passes):
            moved = 0
            for store in self.stores.values():
                moved += Dispatcher(store, transport).drain().attempted
            if moved == 0:
                return

    def _chain(self) -> tuple[str, str, str]:
        origin = self.a.remember(
            agent_id="a",
            content="valve 7 is upstream of the pump",
            type=MemoryType.SEMANTIC,
            auto_activate=True,
        )
        at_b = offer(self.a, origin, self.b, "b", activate=True).imported_memory_id
        at_c = offer(self.b, at_b, self.c, "c", activate=True).imported_memory_id
        self.assertIsNotNone(at_b)
        self.assertIsNotNone(at_c)
        return origin, at_b, at_c

    # --- the share record ------------------------------------------------

    def test_offer_records_the_recipient_store(self) -> None:
        origin, at_b, at_c = self._chain()
        self.assertEqual(self.a.shared_with(origin), {self.b.store_id: at_b})
        self.assertEqual(self.b.shared_with(at_b), {self.c.store_id: at_c})
        # C re-shared to nobody, so it forwards to nobody.
        self.assertEqual(self.c.shared_with(at_c), {})

    def test_share_record_survives_a_projection_rebuild(self) -> None:
        """It is a projection of the log, not a side table."""
        origin, at_b, _ = self._chain()
        reopened = self._reopen("a")
        self.assertEqual(reopened.shared_with(origin), {self.b.store_id: at_b})

    # --- the two-hop case ------------------------------------------------

    def test_retraction_reaches_two_hops_out(self) -> None:
        origin, at_b, at_c = self._chain()
        self.a.request_retraction(
            origin, reason="contradicted by inspection",
            recipients=[self.b.store_id], basis="contradicted",
        )
        self._drain()
        for store, memory_id, label in (
            (self.a, origin, "origin"), (self.b, at_b, "hop 1"), (self.c, at_c, "hop 2"),
        ):
            with self.subTest(label):
                self.assertIs(
                    store.get(memory_id).lifecycle_state,
                    LifecycleState.QUARANTINED,
                )

    def test_the_origin_never_names_the_store_two_hops_out(self) -> None:
        """The reason this needed building: A cannot address C at all."""
        origin, _, _ = self._chain()
        retraction = self.a.request_retraction(
            origin, reason="wrong", recipients=[self.b.store_id],
        )
        requested = [
            event for event in self.a.log.read()
            if event.type == EventType.RETRACTION_REQUESTED
        ]
        self.assertEqual(len(requested), 1)
        self.assertEqual(requested[0].payload["recipients"], [self.b.store_id])
        self.assertNotIn(self.c.store_id, requested[0].payload["recipients"])
        self.assertEqual(retraction.hop, 0)

    def test_the_forwarded_hop_is_retargeted_and_counted(self) -> None:
        origin, at_b, _ = self._chain()
        self.a.request_retraction(
            origin, reason="wrong", recipients=[self.b.store_id],
        )
        Dispatcher(self.a, self._transport()).drain()

        onward = self.b.outbox.due(now_ms())
        self.assertEqual(len(onward), 1)
        forwarded = onward[0].retraction
        # Same campaign, different target. Both halves matter: the campaign is
        # what deduplicates, the target is what the recipient can actually find.
        self.assertEqual(forwarded.origin_store_id, self.a.store_id)
        self.assertEqual(forwarded.origin_memory_id, origin)
        self.assertEqual(forwarded.applies_to_store, self.b.store_id)
        self.assertEqual(forwarded.applies_to_memory, at_b)
        self.assertEqual(forwarded.hop, 1)
        self.assertEqual(forwarded.forwarded_by, self.b.store_id)

    def test_forwarding_intent_commits_with_the_withdrawal(self) -> None:
        """A crash after applying must not lose what is owed downstream.

        The same guarantee `request_retraction` makes at the origin, one hop
        out. Simulated the way it happens: the process stops and a new
        `MemoryFabric` opens the same file.
        """
        origin, at_b, _ = self._chain()
        self.a.request_retraction(
            origin, reason="wrong", recipients=[self.b.store_id],
        )
        Dispatcher(self.a, self._transport()).drain()

        reopened = self._reopen("b")
        self.assertIs(
            reopened.get(at_b).lifecycle_state, LifecycleState.QUARANTINED
        )
        owed = reopened.outbox.pending()
        self.assertEqual([row.recipient for row in owed], [self.c.store_id])

    # --- the cases that go wrong ----------------------------------------

    def test_a_diamond_withdraws_both_copies(self) -> None:
        """A reaches C directly *and* through B. Both copies must go.

        This is where the old deduplication key was unsafe rather than merely
        incomplete. Keyed on the campaign alone, whichever of the two arrivals
        landed first recorded its outcome for both, so the second — a real
        retraction of a real copy — was answered "already handled" and C went on
        exposing knowledge the origin had withdrawn.
        """
        origin = self.a.remember(
            agent_id="a", content="valve 7 is upstream of the pump",
            type=MemoryType.SEMANTIC, auto_activate=True,
        )
        at_b = offer(self.a, origin, self.b, "b", activate=True).imported_memory_id
        from_b = offer(self.b, at_b, self.c, "c", activate=True).imported_memory_id
        from_a = offer(self.a, origin, self.c, "c", activate=True).imported_memory_id
        self.assertNotEqual(from_a, from_b)

        self.a.request_retraction(
            origin, reason="wrong",
            recipients=[self.b.store_id, self.c.store_id],
        )
        self._drain()
        for label, memory_id in (("via B", from_b), ("direct", from_a)):
            with self.subTest(label):
                self.assertIs(
                    self.c.get(memory_id).lifecycle_state,
                    LifecycleState.QUARANTINED,
                )

    def test_a_cycle_terminates_without_reaching_the_hop_limit(self) -> None:
        """A → B → C → A, with A holding a re-import of its own memory.

        Termination has to come from deduplication, not from `MAX_HOPS`: the
        limit is a backstop whose job is to be a bug report. So this asserts
        both that it converges *and* that no hop-limit rejection was recorded.
        """
        origin = self.a.remember(
            agent_id="a", content="valve 7 is upstream of the pump",
            type=MemoryType.SEMANTIC, auto_activate=True,
        )
        at_b = offer(self.a, origin, self.b, "b", activate=True).imported_memory_id
        at_c = offer(self.b, at_b, self.c, "c", activate=True).imported_memory_id
        back_at_a = offer(self.c, at_c, self.a, "a", activate=True).imported_memory_id

        self.a.request_retraction(
            origin, reason="wrong", recipients=[self.b.store_id],
        )
        self._drain(passes=8)

        for label, store, memory_id in (
            ("hop 1", self.b, at_b),
            ("hop 2", self.c, at_c),
            ("hop 3, back at the origin", self.a, back_at_a),
        ):
            with self.subTest(label):
                self.assertIs(
                    store.get(memory_id).lifecycle_state,
                    LifecycleState.QUARANTINED,
                )

        for store in self.stores.values():
            codes = [
                event.payload.get("rejection_code")
                for event in store.log.read()
                if event.type == EventType.RETRACTION_REJECTED
            ]
            self.assertNotIn(RejectionCode.HOP_LIMIT.value, codes)
        # And nothing is still owed: the system is at rest, not oscillating.
        self.assertEqual(
            [row for store in self.stores.values() for row in store.outbox.pending()],
            [],
        )

    def test_the_hop_limit_records_a_rejection(self) -> None:
        origin, at_b, _ = self._chain()
        retraction = self.a.request_retraction(
            origin, reason="wrong", recipients=[self.b.store_id],
        )
        # Arrive at B already at the limit. Still targeted at the origin,
        # because B's copy *was* imported from the origin — a retraction
        # retargeted at B could not apply at B at all, which is the thing the
        # per-hop target exists to express.
        exhausted = replace(retraction, hop=MAX_HOPS)
        ack = self.b.receive_retraction(exhausted)

        self.assertIs(ack.state, PropagationState.ENFORCED)
        self.assertIs(self.b.get(at_b).lifecycle_state, LifecycleState.QUARANTINED)
        # Withdrawn locally, but explicitly *not* forwarded, and the refusal to
        # forward is in the log rather than implied by an empty outbox.
        self.assertEqual(self.b.outbox.pending(), [])
        codes = [
            event.payload.get("rejection_code")
            for event in self.b.log.read()
            if event.type == EventType.RETRACTION_REJECTED
        ]
        self.assertIn(RejectionCode.HOP_LIMIT.value, codes)

    def test_a_locally_derived_conclusion_downstream_is_not_withdrawn(self) -> None:
        """The project's actual question, two hops out.

        `derive` inherits its parent's context, federation origin record
        included, so a conclusion drawn locally from an import looks exactly
        like a second copy of that import to anything matching on the origin
        key. That bug has now appeared twice (`descendants_of`, `_imports_of`);
        forwarding gives it a third place to appear, one hop further from
        anyone who would notice.
        """
        origin, at_b, at_c = self._chain()
        conclusion = self.c.derive(
            agent_id="c",
            content="so the pump inherits valve 7's pressure limit",
            parents=[at_c],
            type=MemoryType.SEMANTIC,
        )
        self.c.validate(conclusion, actor="c")
        self.assertIsNot(
            self.c.get(conclusion).provenance.method, ProvenanceMethod.IMPORTED
        )

        self.a.request_retraction(
            origin, reason="wrong", recipients=[self.b.store_id],
            basis="contradicted",
        )
        self._drain()

        self.assertIs(self.c.get(at_c).lifecycle_state, LifecycleState.QUARANTINED)
        # The conclusion had one premise and lost it, so it is contested rather
        # than active — and contested rather than deleted, which is the point.
        self.assertIsNot(
            self.c.get(conclusion).lifecycle_state, LifecycleState.DELETED
        )

    def test_an_unrelated_memory_downstream_is_untouched(self) -> None:
        origin, _, at_c = self._chain()
        unrelated = self.c.remember(
            agent_id="c", content="the east gate closes at 1800",
            type=MemoryType.SEMANTIC, auto_activate=True,
        )
        self.a.request_retraction(
            origin, reason="wrong", recipients=[self.b.store_id],
        )
        self._drain()
        self.assertIs(self.c.get(at_c).lifecycle_state, LifecycleState.QUARANTINED)
        self.assertIs(self.c.get(unrelated).lifecycle_state, LifecycleState.ACTIVE)

    def test_a_refused_offer_creates_no_forwarding_obligation(self) -> None:
        """A refusal must not leave a delivery that can never succeed.

        Otherwise `pending()` — which an operator is meant to be able to act on
        — fills with retractions owed to stores that never held anything, and
        the signal an operator needs is buried under noise that is correct to
        ignore. The share record has to be written where the offer is
        *accepted*, not where it is attempted.
        """
        refusing = self._store("d")
        origin = self.a.remember(
            agent_id="a",
            content="open valve 7, then start the pump",
            # Procedural, because a federated procedure runs with the
            # recipient's tools and capability scoping is therefore a denial
            # rather than a warning (SECURITY.md T4).
            type=MemoryType.PROCEDURAL,
            capabilities=frozenset({"site:north"}),
            auto_activate=True,
        )
        # Nothing is granted, so `rule_capabilities_must_be_granted` refuses.
        # `offer` grants the same capabilities to both checks, so this is the
        # sender's refusal; the assertion is about what a refusal must *not*
        # leave behind, which is the same either way.
        result = offer(self.a, origin, refusing, "d")
        self.assertFalse(result.accepted)
        self.assertIsNone(result.imported_memory_id)
        self.assertEqual(self.a.shared_with(origin), {})

        self.a.request_retraction(
            origin, reason="wrong", recipients=[refusing.store_id],
        )
        self._drain()
        # The origin's own recipient list named it, so one delivery exists and
        # is answered "no import held". What must not exist is a *forwarded*
        # delivery invented from a share that never happened.
        self.assertEqual(refusing.outbox.pending(), [])


class InboxMigrationTests(unittest.TestCase):
    """Schema 0.3.0 stores must open, and keep deduplicating."""

    def test_an_existing_inbox_gains_the_target_key(self) -> None:
        import sqlite3

        from memory_fabric.outbox import Outbox

        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "old.db"
            conn = sqlite3.connect(path)
            conn.row_factory = sqlite3.Row
            with conn:
                conn.executescript(
                    """
                    CREATE TABLE inbox (
                        origin_store_id TEXT    NOT NULL,
                        retraction_id   TEXT    NOT NULL,
                        origin_sequence INTEGER NOT NULL,
                        outcome         TEXT    NOT NULL,
                        detail          TEXT    NOT NULL DEFAULT '',
                        received_ms     INTEGER NOT NULL,
                        PRIMARY KEY (origin_store_id, retraction_id)
                    );
                    """
                )
                conn.execute(
                    "INSERT INTO inbox VALUES ('st_old', 'rt_old', 3, 'applied', 'x', 1)"
                )

            Outbox(conn)  # opening runs the migration

            columns = {row[1] for row in conn.execute("PRAGMA table_info(inbox)")}
            self.assertIn("target_key", columns)
            row = conn.execute("SELECT * FROM inbox").fetchone()
            # Carried, with an empty target key: every 0.3.0 row was a hop-0
            # retraction whose target *was* the origin, so a re-delivery of one
            # computes the same empty key and still deduplicates.
            self.assertEqual(row["retraction_id"], "rt_old")
            self.assertEqual(row["target_key"], "")
            self.assertEqual(row["outcome"], "applied")
            conn.close()


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
