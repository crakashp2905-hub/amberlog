"""min_independent_sources > 1 is enforced without also listing the check (found by C2)."""

from __future__ import annotations

import unittest

from memory_fabric import MemoryFabric
from memory_fabric.actions import ActionGate, ActionPolicy, ToolRule
from memory_fabric.certificates import INSUFFICIENT_INDEPENDENT_SUPPORT


class MinSourcesEnforced(unittest.TestCase):
    def setUp(self) -> None:
        self.f = MemoryFabric(auto_activate=True)
        self.addCleanup(self.f.close)
        self.a = self.f.remember("s1", "Valve V-7 pressure reads 4 bar.", scope="team")
        self.b = self.f.remember("s2", "Gauge G-2 on valve V-7 shows 4 bar.", scope="team")

    def gate(self, n: int) -> ActionGate:
        return ActionGate(self.f, ActionPolicy(
            tools={"t": ToolRule("t", min_independent_sources=n)},
            grants={"op": frozenset({"t"})}))

    def test_a_tool_rule_asking_for_two_refuses_one(self) -> None:
        d = self.gate(2).authorize("t", "op", self.f.certify("x", [self.a], "op"))
        self.assertFalse(d.allowed)
        self.assertIn(INSUFFICIENT_INDEPENDENT_SUPPORT, d.reason_codes)

    def test_two_independent_sources_pass(self) -> None:
        self.assertTrue(self.gate(2).authorize("t", "op",
                                               self.f.certify("y", [self.a, self.b], "op")).allowed)

    def test_a_certificate_asking_for_two_is_enforced_by_the_verifier(self) -> None:
        cert = self.f.certify("z", [self.a], "op", min_independent_sources=2)
        self.assertFalse(self.f.verify_certificate(cert, "op").ok)

    def test_one_source_still_needs_nothing_more(self) -> None:
        self.assertTrue(self.gate(1).authorize("t", "op", self.f.certify("w", [self.a], "op")).allowed)


if __name__ == "__main__":
    unittest.main()
