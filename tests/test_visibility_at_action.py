"""A token or certificate stops working the moment its memory stops being visible to the agent.

The audit concern: the action-time re-check (`Enforcer.verify_at_action`)
called `check` without the agent, and `visible_to(memory, None)` is the
operator's view, so scope was never re-checked at action time. A private
memory an agent could read through a collection stayed usable after the
agent's access was revoked. Each test is one way visibility narrows.
"""

from __future__ import annotations

import unittest

from amberlog import Amberlog, sdk
from amberlog.actions import ActionGate, ActionPolicy, ToolRule
from amberlog.enforcement import RiskLevel


class VisibilityChanges(unittest.TestCase):
    def setUp(self) -> None:
        self.f = Amberlog(":memory:", auto_activate=True)
        self.addCleanup(self.f.close)
        self.mid = self.f.remember("alice", "Valve V7 opens below 4 bar.")  # private to alice
        self.f.collection_add("ops", self.mid, actor="lead")
        self.f.collection_grant("ops", "bob", ["read"], actor="lead")
        hits = self.f.retrieve("bob", "valve V7 bar", k=3)
        self.assertIn(self.mid, [m.id for m in hits.exposed], "bob can read it via the collection")
        self.exposure = self.f.use(self.mid, agent_id="bob").token

    def assert_unusable(self) -> None:
        decision = self.f.verify_before_action(self.exposure, "bob", risk=RiskLevel.HIGH)
        self.assertFalse(decision.usable, decision.reason_code)

    def test_usable_while_visible(self) -> None:
        self.assertTrue(self.f.verify_before_action(self.exposure, "bob").usable)

    def test_revoking_the_grant_stops_the_token(self) -> None:
        self.f.collection_revoke("ops", "bob", actor="lead")
        self.assert_unusable()

    def test_removing_the_memory_from_the_collection_stops_the_token(self) -> None:
        self.f.collection_remove("ops", self.mid, actor="lead")
        self.assert_unusable()

    def test_the_sdk_verify_agrees(self) -> None:
        bob = sdk.agent(self.f, "bob")
        usable = [h for h in bob.recall("valve V7 bar") if h.memory_id == self.mid][0]
        self.f.collection_revoke("ops", "bob", actor="lead")
        self.assertFalse(bob.verify(usable).usable)

    def test_a_certificate_stops_at_the_gate(self) -> None:
        cert = self.f.certify("open-v7", [self.mid], "bob")
        gate = ActionGate(self.f, ActionPolicy(tools={"open": ToolRule("open")},
                                               grants={"bob": frozenset({"open"})}))
        self.assertTrue(gate.authorize("open", "bob", cert).allowed)
        self.f.collection_revoke("ops", "bob", actor="lead")
        self.assertFalse(gate.authorize("open", "bob", cert).allowed)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
