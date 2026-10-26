"""pilot-report: counts from the log, no content, and a plain readiness check."""

from __future__ import annotations

import json
import unittest

from memory_fabric import MemoryFabric
from memory_fabric.actions import ActionGate, ActionPolicy, ToolRule
from memory_fabric.pilot import content_free, readiness, report

SECRET_NOTE = "valve 7 on the north manifold is safe to open below 4 bar"


class PilotReport(unittest.TestCase):
    def setUp(self) -> None:
        self.f = MemoryFabric(":memory:", auto_activate=True)
        self.addCleanup(self.f.close)
        self.m = self.f.remember("ana", SECRET_NOTE, scope="team")
        self.f.remember("ben", "The north manifold was inspected on Monday.", scope="team")
        self.f.retrieve("ben", "north manifold valve 7", k=3)
        gate = ActionGate(self.f, ActionPolicy(tools={"open_valve": ToolRule("open_valve")},
                                               grants={"ops": frozenset({"open_valve"})}))
        cert = self.f.certify("open-7", [self.m], "ops")
        gate.execute("open_valve", "ops", lambda key: "opened", cert, key="k1")
        self.f.quarantine(self.m, reason="the limit is 3 bar", actor="op")
        gate.execute("open_valve", "ops", lambda key: "opened", cert, key="k2")

    def test_counts_what_happened(self) -> None:
        rep = report(self.f)
        self.assertEqual(rep["withdrawn"], 1)
        self.assertEqual(rep["actions_allowed"], 1)
        self.assertEqual(rep["acted_on_evidence_later_withdrawn"], 1)
        self.assertGreaterEqual(rep["blocked_on_evidence"], 1)
        self.assertEqual(rep["exposures_after_withdrawal"], 0)

    def test_holds_no_content_and_hides_agent_names(self) -> None:
        rep = report(self.f)
        blob = json.dumps(rep)
        self.assertTrue(rep["content_free"])
        self.assertNotIn("manifold", blob)
        self.assertNotIn("ana", rep["agents"])
        self.assertIn("ana", report(self.f, names=True)["agents"])

    def test_the_content_check_catches_leaked_text(self) -> None:
        self.assertFalse(content_free(self.f, {"note": SECRET_NOTE}))

    def test_readiness_says_what_is_missing(self) -> None:
        self.assertTrue(all(ok for ok, _ in readiness(report(self.f))))
        thin = MemoryFabric(":memory:", auto_activate=True)
        self.addCleanup(thin.close)
        thin.remember("solo", "Only one agent here.", scope="team")
        failing = [line for ok, line in readiness(report(thin)) if not ok]
        self.assertTrue(any("at least 2" in line for line in failing))
        self.assertTrue(any("correction" in line for line in failing))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
