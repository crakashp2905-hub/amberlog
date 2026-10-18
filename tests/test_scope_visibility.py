"""Scope is enforced on reads: private means the agent that wrote it.

Until 2026-10-18 retrieval checked only lifecycle and tenant, so a validated
memory written `private` -- a restricted one included -- was returned to every
agent in its tenant, although the specification and glossary define scope as
visibility (docs/SECURITY_REVIEW.md F10). These tests pin the enforced rule on
every path an agent reads by: retrieval, the enforced read, certificates, and
the agent-facing SDK.
"""

from __future__ import annotations

import unittest

from memory_fabric import MemoryFabric
from memory_fabric.enforcement import NOT_VISIBLE, RiskLevel
from memory_fabric.fabric import PolicyViolation
from memory_fabric.model import FirewallDecision, Scope
from memory_fabric.sdk import agent, operator


class PrivateMeansTheWriter(unittest.TestCase):
    def setUp(self) -> None:
        self.fabric = MemoryFabric(":memory:", auto_activate=True)
        self.addCleanup(self.fabric.close)
        self.mine = self.fabric.remember("ana", "valve 7 sticks below 4 C")

    def ids(self, agent_id: str, query: str = "valve 7 sticks") -> list[str]:
        return [m.id for m in self.fabric.retrieve(agent_id, query, k=5).exposed]

    def test_the_writer_retrieves_it(self) -> None:
        self.assertIn(self.mine, self.ids("ana"))

    def test_another_agent_in_the_tenant_does_not(self) -> None:
        self.assertNotIn(self.mine, self.ids("ben"))

    def test_the_enforced_read_refuses_without_revealing_anything(self) -> None:
        read = self.fabric.use(self.mine, "ben", risk=RiskLevel.HIGH)
        self.assertFalse(read.usable)
        self.assertEqual(read.decision.reason_code, NOT_VISIBLE)
        self.assertEqual(read.decision.version, 0)
        self.assertIsNone(read.memory)

    def test_sharing_to_the_team_opens_it(self) -> None:
        ruling = self.fabric.share(self.mine, Scope.TEAM, actor="reviewer")
        self.assertIs(ruling.decision, FirewallDecision.ALLOW)
        self.assertIn(self.mine, self.ids("ben"))

    def test_an_operator_is_not_agent_scoped(self) -> None:
        self.assertTrue(self.fabric.enforcer.check(self.mine).usable)

    def test_a_certificate_for_another_agent_does_not_verify(self) -> None:
        cert = self.fabric.certify("c", [self.mine], "ben")
        self.assertFalse(self.fabric.verify_certificate(cert, "ben").ok)


class RestrictedStaysPrivate(unittest.TestCase):
    def setUp(self) -> None:
        self.fabric = MemoryFabric(":memory:", auto_activate=True)
        self.addCleanup(self.fabric.close)

    def test_it_cannot_be_written_wider(self) -> None:
        with self.assertRaises(PolicyViolation):
            self.fabric.remember("ana", "salary bands", security_class="restricted",
                                 scope="team")

    def test_it_cannot_be_shared_wider(self) -> None:
        mid = self.fabric.remember("ana", "salary bands", security_class="restricted")
        self.assertIs(self.fabric.share(mid, Scope.TEAM).decision, FirewallDecision.DENY)
        self.assertNotIn(mid, [m.id for m in self.fabric.retrieve("ben", "salary bands").exposed])


class DerivedIsNoWiderThanItsPremises(unittest.TestCase):
    def test_a_conclusion_from_a_private_premise_stays_private(self) -> None:
        fabric = MemoryFabric(":memory:", auto_activate=True)
        self.addCleanup(fabric.close)
        premise = fabric.remember("ana", "valve 7 sticks below 4 C")
        conclusion = fabric.derive("ana", "warm valve 7 before winter starts",
                                   parents=[premise], scope="team")
        self.assertIs(fabric.state.memories[conclusion].scope, Scope.PRIVATE)

    def test_a_conclusion_from_team_premises_can_be_team(self) -> None:
        fabric = MemoryFabric(":memory:", auto_activate=True)
        self.addCleanup(fabric.close)
        premise = fabric.remember("ana", "valve 7 sticks below 4 C", scope="team")
        conclusion = fabric.derive("ana", "warm valve 7 before winter starts",
                                   parents=[premise], scope="team")
        self.assertIs(fabric.state.memories[conclusion].scope, Scope.TEAM)


class TheAgentFacingSdk(unittest.TestCase):
    def test_an_agents_write_is_its_own_until_an_operator_shares_it(self) -> None:
        fabric = MemoryFabric(":memory:")
        self.addCleanup(fabric.close)
        ana, ben, op = agent(fabric, "ana"), agent(fabric, "ben"), operator(fabric, "op")
        mid = ana.remember("pump 3 needs a new seal")
        op.validate(mid)
        self.assertEqual([m.memory_id for m in ben.recall("pump 3 seal")], [])
        self.assertIn(mid, [m.memory_id for m in ana.recall("pump 3 seal")])
        op.share(mid, "team")
        self.assertIn(mid, [m.memory_id for m in ben.recall("pump 3 seal")])


class TheUpgradeCommand(unittest.TestCase):
    def test_it_restores_tenant_visibility_except_where_a_rule_forbids_it(self) -> None:
        import contextlib
        import io
        import os
        import tempfile

        from memory_fabric.cli import main

        with tempfile.TemporaryDirectory() as tmp:
            db = os.path.join(tmp, "s.db")
            fabric = MemoryFabric(db, auto_activate=True)
            plain = fabric.remember("ana", "pump 3 needs a new seal")
            restricted = fabric.remember("ana", "salary bands", security_class="restricted")
            fabric.close()
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = main(["--db", db, "share", "--all-private-active", "--actor", "op"])
            self.assertEqual(code, 0)
            self.assertIn("shared 1", out.getvalue())
            self.assertIn(restricted, out.getvalue(), "the refusal names what it refused")
            reopened = MemoryFabric(db)
            try:
                self.assertIs(reopened.state.memories[plain].scope, Scope.TEAM)
                self.assertIs(reopened.state.memories[restricted].scope, Scope.PRIVATE)
            finally:
                reopened.close()


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
