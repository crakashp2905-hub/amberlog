"""Sharing between stores on different machines: a signed offer over HTTP, then a retraction."""

from __future__ import annotations

import unittest

from memory_fabric import LifecycleState, MemoryFabric, correction
from memory_fabric.dispatcher import Dispatcher
from memory_fabric.federation import offer_remote
from memory_fabric.governance.firewall import (Firewall, rule_capabilities_must_be_granted,
                                               rule_must_be_active, rule_restricted_stays_private)
from memory_fabric.transport import HttpTransport, Peer, PeerRegistry, TransportError, serve

KEY = b"remote-offer-shared-key-000000000"


def store() -> MemoryFabric:
    return MemoryFabric(":memory:", auto_activate=True, firewall=Firewall(rules=(
        rule_restricted_stays_private, rule_must_be_active, rule_capabilities_must_be_granted)))


class RemoteOffer(unittest.TestCase):
    def setUp(self) -> None:
        self.plant, self.hq = store(), store()
        self.addCleanup(self.plant.close)
        self.addCleanup(self.hq.close)
        self.served = serve(self.hq, PeerRegistry({self.plant.store_id: Peer(
            self.plant.store_id, "unused", KEY)}))
        self.addCleanup(self.served.close)
        self.transport = HttpTransport(PeerRegistry({self.hq.store_id: Peer(
            self.hq.store_id, self.served.endpoint, KEY)}), self.plant.store_id)
        self.note = self.plant.remember("tech", "Line 3 conveyor belt speed is 40 m/min.",
                                        scope="team")

    def test_offer_lands_as_a_candidate_from_the_peer_with_provenance(self) -> None:
        result = offer_remote(self.plant, self.note, self.transport, self.hq.store_id, "lead")
        self.assertTrue(result.accepted, result.reasons)
        imported = self.hq.get(result.imported_memory_id)
        self.assertIs(imported.lifecycle_state, LifecycleState.CANDIDATE,
                      "a remote sender cannot activate its memory")
        self.assertEqual(imported.provenance.created_by, f"peer:{self.plant.store_id}",
                         "the sender cannot choose a local agent id")
        origin = imported.context["federation"]
        self.assertEqual((origin["store"], origin["memory_id"]), (self.plant.store_id, self.note))
        self.assertIn(self.hq.store_id, self.plant.notice_recipients("tech"))

    def test_a_correction_reaches_the_remote_copy(self) -> None:
        result = offer_remote(self.plant, self.note, self.transport, self.hq.store_id, "x")
        self.hq.validate(result.imported_memory_id, actor="hq-reviewer")
        correction.apply(self.plant, self.note, reason="re-measured: 35 m/min", actor="lead")
        Dispatcher(self.plant, self.transport).run_once()
        self.assertIs(self.hq.get(result.imported_memory_id).lifecycle_state,
                      LifecycleState.QUARANTINED)

    def test_the_same_offer_twice_is_one_import(self) -> None:
        first = offer_remote(self.plant, self.note, self.transport, self.hq.store_id, "x")
        second = offer_remote(self.plant, self.note, self.transport, self.hq.store_id, "x")
        self.assertEqual(first.imported_memory_id, second.imported_memory_id)
        self.assertEqual(len(self.hq.state.memories), 1)

    def test_a_wrong_key_imports_nothing(self) -> None:
        wrong = HttpTransport(PeerRegistry({self.hq.store_id: Peer(
            self.hq.store_id, self.served.endpoint, b"not-the-key")}), self.plant.store_id)
        with self.assertRaises(TransportError) as caught:
            offer_remote(self.plant, self.note, wrong, self.hq.store_id, "x")
        self.assertTrue(caught.exception.permanent)
        self.assertEqual(len(self.hq.state.memories), 0)

    def test_the_import_is_untrusted_until_reviewed(self) -> None:
        result = offer_remote(self.plant, self.note, self.transport, self.hq.store_id, "x")
        self.hq.validate(result.imported_memory_id, actor="hq-reviewer")
        self.assertEqual(self.hq.authority(result.imported_memory_id).trust, "untrusted")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
