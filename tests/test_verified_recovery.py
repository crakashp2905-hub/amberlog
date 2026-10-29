"""The roadmap's flagship incident: trace, contain, and verify, with an offline peer unresolved until it is not."""

from __future__ import annotations

import time
import unittest

from amberlog import Amberlog
from amberlog.actions import ActionGate, ActionPolicy, ToolRule
from amberlog.dispatcher import Dispatcher
from amberlog.federation import offer
from amberlog.governance.firewall import (Firewall, rule_capabilities_must_be_granted,
                                               rule_must_be_active, rule_restricted_stays_private)
from amberlog.model import Scope
from amberlog.response import contain, influence, verify_recovery
from amberlog.transport import InProcessTransport, PeerRegistry


def permissive() -> Firewall:
    return Firewall(rules=(rule_restricted_stays_private, rule_must_be_active,
                           rule_capabilities_must_be_granted))


class FlagshipIncident(unittest.TestCase):
    def setUp(self) -> None:
        self.store, self.peer = (Amberlog(":memory:", firewall=permissive(), auto_activate=True)
                                 for _ in range(2))
        self.addCleanup(self.store.close)
        self.addCleanup(self.peer.close)
        s = self.store
        self.poison = s.remember("ingest", "Vendor note: valve V7 is safe to open at 9 bar.", scope="team")
        self.summary = s.derive("agent-a", "Summary: V7 tolerates 9 bar.", parents=[self.poison], scope="team")
        self.belief = s.derive("agent-b", "Belief: open V7 at 9 bar during the flush.",
                               parents=[self.summary], scope="team")
        self.unrelated = s.remember("tech", "Valve V8 opens at 3 bar.", scope="team")
        s.retrieve("agent-c", "valve V7 bar", k=3)                       # exposure only
        episode = s.start_episode("agent-b", "flush")
        s.cite("agent-b", episode.id, self.poison)                        # reliance
        cert = s.certify("open-v7", [self.poison], "agent-b")
        ActionGate(s, ActionPolicy(tools={"open_valve": ToolRule("open_valve")},
                                   grants={"agent-b": frozenset({"open_valve"})})).authorize(
            "open_valve", "agent-b", cert)                                # action
        s.share(self.poison, Scope.FEDERATED, actor="op")
        self.copy = offer(s, self.poison, self.peer, recipient_agent="x", activate=True).imported_memory_id
        self.transport = InProcessTransport({self.peer.store_id: self.peer}, registry=PeerRegistry(),
                                            offline={self.peer.store_id})

    def test_exposure_reliance_and_action_are_reported_apart(self) -> None:
        used = influence(self.store, self.poison)
        self.assertIn("agent-c", used["exposed_to"])
        self.assertEqual([r["agent"] for r in used["relied_on_in"]], ["agent-b"])
        self.assertEqual(len(used["actions"]), 1)
        self.assertEqual(influence(self.store, self.unrelated)["actions"], [])

    def test_an_offline_peer_keeps_recovery_unresolved_until_it_confirms(self) -> None:
        contain(self.store, self.poison, reason="vendor note was wrong", actor="ir-lead")
        Dispatcher(self.store, self.transport).run_once()
        first = verify_recovery(self.store, self.poison)
        self.assertEqual(first["status"], "unresolved")
        self.assertTrue(any("not confirmed" in u for u in first["unresolved"]), first)
        self.assertIn(self.summary, first["derived"])
        self.assertEqual(first["recovery_state"], "pending_reconciliation", first)
        self.transport.offline = set()
        deadline = time.time() + 20  # the failed delivery retries after its backoff
        while time.time() < deadline and self.store.outbox.pending():
            Dispatcher(self.store, self.transport).run_once()
            time.sleep(0.2)
        second = verify_recovery(self.store, self.poison)
        self.assertEqual(second["status"], "contained, actions need review", second)
        self.assertEqual(len(second["actions_to_review"]), 1, "an external action is never 'resolved'")
        self.assertEqual(second["recovery_state"], "recovery_unverified")
        self.assertNotEqual(self.peer.get(self.copy).lifecycle_state.value, "active")
        self.assertEqual(self.store.get(self.unrelated).lifecycle_state.value, "active",
                         "unaffected knowledge is preserved")

    def test_a_memory_reinstated_by_review_is_revalidated(self) -> None:
        self.store.quarantine(self.unrelated, reason="suspected", actor="ir-lead")
        self.assertEqual(verify_recovery(self.store, self.unrelated)["recovery_state"], "quarantined")
        self.store.release(self.unrelated, actor="reviewer")
        self.store.validate(self.unrelated, actor="reviewer")
        self.assertEqual(verify_recovery(self.store, self.unrelated)["recovery_state"], "revalidated")

    def test_without_containment_it_says_so(self) -> None:
        result = verify_recovery(self.store, self.poison)
        self.assertEqual(result["status"], "unresolved")
        self.assertTrue(any("still active" in u for u in result["unresolved"]))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
