"""A memory shared around a cycle is not imported back into a store that holds it."""

from __future__ import annotations

import unittest

from memory_fabric import MemoryFabric
from memory_fabric.federation import imported_from, offer
from memory_fabric.governance.firewall import (Firewall, rule_capabilities_must_be_granted,
                                               rule_must_be_active, rule_restricted_stays_private)
from memory_fabric.model import Scope


def permissive() -> Firewall:
    return Firewall(rules=(rule_restricted_stays_private, rule_must_be_active,
                           rule_capabilities_must_be_granted))


class EchoImport(unittest.TestCase):
    def setUp(self) -> None:
        self.a, self.b, self.c = (MemoryFabric(":memory:", firewall=permissive(),
                                               auto_activate=True) for _ in range(3))
        for store in (self.a, self.b, self.c):
            self.addCleanup(store.close)
        self.mid = self.a.remember("ana", "valve A runs at 4 bar", scope="team")
        self.a.share(self.mid, Scope.FEDERATED, actor="op")

    def hop(self, source: MemoryFabric, memory_id: str, target: MemoryFabric):
        source.share(memory_id, Scope.FEDERATED, actor="op")
        return offer(source, memory_id, target, recipient_agent="x", activate=True)

    def test_the_chain_is_recorded_hop_by_hop(self) -> None:
        at_b = self.hop(self.a, self.mid, self.b).imported_memory_id
        at_c = self.hop(self.b, at_b, self.c).imported_memory_id
        self.assertEqual(imported_from(self.b, at_b)["chain"], [self.a.store_id])
        self.assertEqual(imported_from(self.c, at_c)["chain"], [self.a.store_id, self.b.store_id])

    def test_a_memory_does_not_come_home_as_an_import(self) -> None:
        at_b = self.hop(self.a, self.mid, self.b).imported_memory_id
        result = self.hop(self.b, at_b, self.a)
        self.assertFalse(result.accepted)
        self.assertIn("provenance chain", result.reasons[0])
        self.assertEqual(len(self.a.state.memories), 1)

    def test_nor_into_any_store_it_passed_through(self) -> None:
        at_b = self.hop(self.a, self.mid, self.b).imported_memory_id
        at_c = self.hop(self.b, at_b, self.c).imported_memory_id
        self.assertFalse(self.hop(self.c, at_c, self.b).accepted)
        self.assertFalse(self.hop(self.c, at_c, self.a).accepted)

    def test_an_import_recorded_before_the_chain_still_names_its_origin(self) -> None:
        at_b = self.hop(self.a, self.mid, self.b).imported_memory_id
        memory = self.b.get(at_b)
        legacy = dict(memory.context)
        legacy["federation"] = {k: v for k, v in legacy["federation"].items() if k != "chain"}
        from memory_fabric.federation import _chain
        self.assertEqual(_chain(memory.evolve(context=legacy)), [self.a.store_id])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
