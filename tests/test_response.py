"""Guided incident response, end to end on one poisoning."""

from __future__ import annotations

import unittest

from memory_fabric import MemoryFabric
from memory_fabric.actions import ActionGate, ActionPolicy, ToolRule
from memory_fabric.governance.firewall import (Firewall, rule_capabilities_must_be_granted,
                                               rule_must_be_active, rule_restricted_stays_private)
from memory_fabric.model import LifecycleState, Scope
from memory_fabric.response import assess, candidates, contain, record, record_markdown


class APoisoning(unittest.TestCase):
    def setUp(self) -> None:
        from memory_fabric.federation import offer

        permissive = Firewall(rules=(rule_restricted_stays_private, rule_must_be_active,
                                     rule_capabilities_must_be_granted))
        self.fabric = MemoryFabric(":memory:", firewall=permissive, auto_activate=True)
        self.other = MemoryFabric(":memory:", firewall=permissive)
        self.addCleanup(self.fabric.close)
        self.addCleanup(self.other.close)
        f = self.fabric
        self.poison = f.remember("mallory", "crane 9 is rated for 40 t", scope="team")
        self.sibling = f.remember("mallory", "crane 9 inspection was waived", scope="team")
        self.honest = f.remember("ana", "crane 9 inspected in March", scope="team")
        self.plan = f.derive("cho", "lift plan: crane 9 can take the 35 t load",
                             parents=[self.poison], scope="team")
        f.retrieve("ben", "crane 9 rated")
        f.share(self.poison, Scope.FEDERATED, actor="op")
        offer(f, self.poison, self.other, recipient_agent="dan")
        gate = ActionGate(f, ActionPolicy(tools={"lift": ToolRule("lift")},
                                          grants={"cho": frozenset({"lift"})}))
        gate.authorize("lift", "cho", f.certify("c", [self.poison], "cho"))

    def test_assessment_shows_the_spread(self) -> None:
        a = assess(self.fabric, self.poison)
        self.assertEqual(a["author"], "mallory")
        self.assertIn(self.sibling, a["author_other_active"])
        self.assertIn("ben", a["seen_by"])
        self.assertEqual([s["store_id"] for s in a["stores"]], [self.other.store_id])
        self.assertIn(self.plan, a["blast_radius"]["would_contest"])
        self.assertEqual(len(a["actions_using_it"]), 1)
        self.assertEqual(a["actions_using_it"][0]["tool"], "lift")
        self.assertTrue(a["actions_using_it"][0]["necessary_source"])

    def test_containment_withdraws_owes_and_points_at_the_author(self) -> None:
        result = contain(self.fabric, self.poison, reason="fabricated rating", actor="sec-lead")
        self.assertIs(self.fabric.state.memories[self.poison].lifecycle_state,
                      LifecycleState.QUARANTINED)
        self.assertIsNot(self.fabric.state.memories[self.plan].lifecycle_state,
                         LifecycleState.ACTIVE)
        self.assertIs(self.fabric.state.memories[self.honest].lifecycle_state,
                      LifecycleState.ACTIVE)
        self.assertEqual(result["owed_to"], [self.other.store_id])
        self.assertIn(self.sibling, result["review_next"])
        again = contain(self.fabric, self.poison, reason="again", actor="sec-lead")
        self.assertTrue(again["already_quarantined"])

    def test_the_record_shows_who_did_what_and_what_is_outstanding(self) -> None:
        from memory_fabric.dispatcher import Dispatcher
        from memory_fabric.transport import InProcessTransport, Peer, PeerRegistry

        contain(self.fabric, self.poison, reason="fabricated rating", actor="sec-lead")
        data = record(self.fabric, self.poison)
        types = [t["type"] for t in data["timeline"]]
        self.assertIn("ActionGated", types)
        self.assertIn("RetractionRequested", types)
        self.assertTrue(any(t["actor"] == "sec-lead" for t in data["timeline"]))
        self.assertEqual([d["store_id"] for d in data["outstanding"]], [self.other.store_id])
        markdown = record_markdown(data)
        self.assertIn("# Incident record", markdown)
        self.assertIn("lift", markdown)
        registry = PeerRegistry({self.fabric.store_id: Peer(self.fabric.store_id, "x", b"k")})
        Dispatcher(self.fabric, InProcessTransport({self.other.store_id: self.other},
                                                   registry=registry)).run_once()
        self.assertEqual(record(self.fabric, self.poison)["outstanding"], [])

    def test_a_screen_quarantine_is_a_candidate(self) -> None:
        leaked = self.fabric.remember("eve", "deploy key " + "AKIA" + "QWER" * 4)
        found = {c["memory_id"]: c["why"] for c in candidates(self.fabric)}
        self.assertIn(leaked, found)
        self.assertTrue(any("ingest screen" in w for w in found[leaked]))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
