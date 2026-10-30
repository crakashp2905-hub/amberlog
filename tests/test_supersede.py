"""A correction travels: copies of an older version are withdrawn, by version."""

from __future__ import annotations

import time
import unittest

from memory_fabric import MemoryFabric
from memory_fabric.dispatcher import Dispatcher
from memory_fabric.federation import offer
from memory_fabric.governance.firewall import (Firewall, rule_capabilities_must_be_granted,
                                               rule_must_be_active, rule_restricted_stays_private)
from memory_fabric.model import LifecycleState, Scope
from memory_fabric.transport import InProcessTransport, PeerRegistry


def permissive() -> Firewall:
    return Firewall(rules=(rule_restricted_stays_private, rule_must_be_active,
                           rule_capabilities_must_be_granted))


class Supersede(unittest.TestCase):
    def setUp(self) -> None:
        self.origin = MemoryFabric(":memory:", firewall=permissive(), auto_activate=True)
        self.recipient = MemoryFabric(":memory:", firewall=permissive())
        self.addCleanup(self.origin.close)
        self.addCleanup(self.recipient.close)
        self.transport = InProcessTransport({self.recipient.store_id: self.recipient},
                                            registry=PeerRegistry())
        self.mid = self.origin.remember("ana", "valve A runs at 4 bar", scope="team")
        self.origin.share(self.mid, Scope.FEDERATED, actor="op")
        self.v1 = self.share()

    def share(self) -> str:
        return offer(self.origin, self.mid, self.recipient, recipient_agent="x",
                     activate=True).imported_memory_id

    def dispatch(self) -> None:
        for _ in range(20):
            Dispatcher(self.origin, self.transport).run_once()
            if not self.origin.outbox.pending():
                return
            time.sleep(0.2)

    def active_texts(self) -> set[str]:
        return {m.content for m in self.recipient.state.memories.values()
                if m.lifecycle_state is LifecycleState.ACTIVE}

    def test_a_correction_replaces_the_copy(self) -> None:
        self.origin.revise(self.mid, "valve A runs at 5 bar", agent_id="ana", reason="correction")
        owed = self.origin.supersede_copies(self.mid, actor="op")
        self.assertEqual([r.origin_memory_version for r in owed], [1])
        self.assertEqual(owed[0].evidence_reference, "superseded by version 2")
        self.dispatch()
        self.share()
        self.assertEqual(self.active_texts(), {"valve A runs at 5 bar"})
        self.assertIs(self.origin.state.memories[self.mid].lifecycle_state, LifecycleState.ACTIVE,
                      "the origin's own current version is not withdrawn")

    def test_it_is_idempotent(self) -> None:
        self.origin.revise(self.mid, "valve A runs at 5 bar", agent_id="ana", reason="correction")
        self.assertEqual(len(self.origin.supersede_copies(self.mid, actor="op")), 1)
        self.assertEqual(self.origin.supersede_copies(self.mid, actor="op"), [])

    def test_an_offline_recipient_catches_up(self) -> None:
        self.transport.offline = {self.recipient.store_id}
        self.origin.revise(self.mid, "valve A runs at 5 bar", agent_id="ana", reason="correction")
        self.origin.supersede_copies(self.mid, actor="op")
        Dispatcher(self.origin, self.transport).run_once()
        self.assertIn("valve A runs at 4 bar", self.active_texts(), "offline: still the old copy")
        self.transport.offline = set()
        self.dispatch()
        self.share()
        self.assertEqual(self.active_texts(), {"valve A runs at 5 bar"})

    def test_concurrent_corrections_delivered_in_reverse_order(self) -> None:
        self.transport.offline = {self.recipient.store_id}
        self.origin.revise(self.mid, "valve A runs at 5 bar", agent_id="ana", reason="correction")
        self.share()  # v2 reaches the recipient directly (an offer is the host's call)
        self.origin.revise(self.mid, "valve A runs at 6 bar", agent_id="ana", reason="again")
        owed = self.origin.supersede_copies(self.mid, actor="op")
        self.assertEqual(sorted(r.origin_memory_version for r in owed), [1, 2])
        for retraction in sorted(owed, key=lambda r: -r.origin_sequence):  # newest first
            self.recipient.receive_retraction(retraction)
        self.share()
        self.assertEqual(self.active_texts(), {"valve A runs at 6 bar"})


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
