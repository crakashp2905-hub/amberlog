"""The shareable pilot report: right counts, no content, no names by default."""

from __future__ import annotations

import json
import unittest

from memory_fabric import MemoryFabric
from memory_fabric.actions import ActionGate, ActionPolicy, ToolRule
from memory_fabric.pilot import report


class TestPilotReport(unittest.TestCase):
    def test_counts_and_privacy(self):
        f = MemoryFabric(":memory:", auto_activate=True)
        self.addCleanup(f.close)
        mid = f.remember("ag_secret_name", "Pump P-14 relief valve is set to 12 bar.", scope="team")
        gate = ActionGate(f, ActionPolicy(tools={"set": ToolRule("set")},
                                          grants={"ag_ops": frozenset({"set"})}))
        cert = f.certify("x", [mid], "ag_ops")
        self.assertTrue(gate.authorize("set", "ag_ops", cert).allowed)
        f.quarantine(mid, reason="wrong", actor="lead", basis="contradicted")
        self.assertFalse(gate.authorize("set", "ag_ops", cert).allowed)
        f.retrieve("ag_reader", "P-14 relief", k=3)
        r = report(f)
        self.assertEqual(r["actions_allowed"], 1)
        self.assertEqual(r["acted_on_evidence_later_withdrawn"], 1)
        self.assertEqual(r["blocked_on_evidence"], 1)
        self.assertEqual(r["exposures_after_withdrawal"], 0)
        text = json.dumps(r)
        self.assertNotIn("Pump", text)
        self.assertNotIn("ag_secret_name", text)
        self.assertNotIn(mid, text)
        self.assertIn("ag_secret_name", json.dumps(report(f, names=True)))


if __name__ == "__main__":
    unittest.main()
