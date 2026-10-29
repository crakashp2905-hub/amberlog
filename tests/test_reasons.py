"""Reason codes read as sentences; the trust badge says what a memory is."""

from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

from amberlog import Amberlog
from amberlog.actions import ActionGate, ActionPolicy, ToolRule
from amberlog.reasons import REASONS, badge, describe, say

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_troubleshooting import codes  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


class TestCoverage(unittest.TestCase):
    def test_every_gate_and_enforcer_code_has_a_sentence(self):
        enforcer = set(re.findall(r'^[A-Z_]+ = "([a-z_]+)"$',
                                  (ROOT / "amberlog/enforcement.py").read_text(), re.M))
        enforcer -= {"low", "medium", "high", "usable", "revalidate", "unknown", "blocked"}
        missing = sorted((codes() | enforcer) - set(REASONS))
        self.assertEqual(missing, [])

    def test_sentences_are_sentences(self):
        for code, (what, todo) in REASONS.items():
            self.assertTrue(what.endswith("."), code)
            self.assertFalse(what.startswith(code), code)
        self.assertEqual(say("made_up_code"), "Made up code.")


class TestDescribe(unittest.TestCase):
    def test_names_the_withdrawn_memory_who_and_why(self):
        f = Amberlog(":memory:", auto_activate=True)
        self.addCleanup(f.close)
        mid = f.remember("ag_inspector", "Pump P-14 relief valve is set to 12 bar.", scope="team")
        gate = ActionGate(f, ActionPolicy(tools={"set_relief": ToolRule("set_relief")},
                                          grants={"ag_ops": frozenset({"set_relief"})}))
        cert = f.certify("P-14 relief is 12 bar", [mid], "ag_ops")
        self.assertTrue(gate.authorize("set_relief", "ag_ops", cert).allowed)
        f.quarantine(mid, reason="vendor re-specified the setting", actor="ops",
                     basis="contradicted")
        decision = gate.authorize("set_relief", "ag_ops", cert)
        self.assertFalse(decision.allowed)
        text = " ".join(describe(f, decision))
        self.assertIn("Pump P-14 relief valve", text)
        self.assertIn("withdrawn by ops", text)
        self.assertIn("vendor re-specified", text)


class TestBadge(unittest.TestCase):
    def test_counts_independent_sources_not_agents(self):
        f = Amberlog(":memory:", auto_activate=True)
        self.addCleanup(f.close)
        a = f.remember("ag_a", "Pump P-14 relief valve is set to 12 bar.", scope="team")
        f.remember("ag_b", "Measured today: the P-14 relief valve setting reads 12 bar.",
                   scope="team")
        b = badge(f, a)
        self.assertEqual(b["source"], "ag_a")
        self.assertEqual(b["independent_sources"], 2)
        self.assertIn("2 independent sources", b["summary"])
        self.assertEqual(b["revised"], 0)


if __name__ == "__main__":
    unittest.main()
