"""A compromised established account changing its own validated fact (LIMITATIONS)."""

from __future__ import annotations

import unittest

from memory_fabric import MemoryFabric
from memory_fabric.actions import EVIDENCE_PROVISIONAL, ActionGate, ActionPolicy, ToolRule
from memory_fabric.validation import assess


class RevisesValidated(unittest.TestCase):
    def setUp(self) -> None:
        self.f = MemoryFabric(auto_activate=True, hold_suspicious=False)
        self.addCleanup(self.f.close)
        for i in range(3):
            self.f.validate(self.f.remember("ag_tech", f"Pump P-{20 + i}: the torque setting is {40 + i} Nm."),
                            actor="reviewer")
        self.old = self.f.remember("ag_tech", "Hoist H-14: the relief pressure is 12 bar.")
        self.f.validate(self.old, actor="reviewer")

    def test_own_change_to_a_vouched_fact_is_provisional_not_suspicious(self) -> None:
        new = self.f.remember("ag_tech", "Hoist H-14: the relief pressure is 31 bar.", scope="team")
        a = assess(self.f, new)
        self.assertEqual(a.level, "provisional")
        self.assertIn("revises_validated", a.signals)

    def test_revalidation_clears_it(self) -> None:
        new = self.f.remember("ag_tech", "Hoist H-14: the relief pressure is 31 bar.", scope="team")
        self.f.validate(new, actor="reviewer")
        self.assertNotIn("revises_validated", assess(self.f, new).signals)

    def test_an_unvouched_fact_changes_freely(self) -> None:
        loose = self.f.remember("ag_tech", "Valve V-9: the trip current is 20 A.")
        new = self.f.remember("ag_tech", "Valve V-9: the trip current is 25 A.")
        self.assertIsNotNone(loose)
        self.assertNotIn("revises_validated", assess(self.f, new).signals)

    def test_self_validation_does_not_count_as_vouching(self) -> None:
        loose = self.f.remember("ag_tech", "Valve V-8: the trip current is 20 A.")
        self.f.validate(loose, actor="ag_tech")
        new = self.f.remember("ag_tech", "Valve V-8: the trip current is 25 A.")
        self.assertNotIn("revises_validated", assess(self.f, new).signals)

    def test_the_gate_can_refuse_it(self) -> None:
        new = self.f.remember("ag_tech", "Hoist H-14: the relief pressure is 31 bar.", scope="team")
        cert = self.f.certify("set-relief", [new], "ag_ops")
        policy = lambda strict: ActionPolicy(  # noqa: E731
            tools={"set_relief": ToolRule("set_relief", refuse_provisional=strict)},
            grants={"ag_ops": frozenset({"set_relief"})})
        lenient = ActionGate(self.f, policy(False)).authorize("set_relief", "ag_ops", cert)
        strict = ActionGate(self.f, policy(True)).authorize("set_relief", "ag_ops", cert)
        self.assertTrue(lenient.allowed)
        self.assertFalse(strict.allowed)
        self.assertIn(EVIDENCE_PROVISIONAL, strict.reason_codes)


if __name__ == "__main__":
    unittest.main()
