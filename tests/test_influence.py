"""Typed influence edges; contaminated, retrieved and confirmed use kept apart."""

from __future__ import annotations

import unittest

from memory_fabric import MemoryFabric, influence
from memory_fabric.actions import ActionGate, ActionPolicy, ToolRule


class Influence(unittest.TestCase):
    def setUp(self) -> None:
        self.f = MemoryFabric(":memory:", auto_activate=True)
        self.addCleanup(self.f.close)
        self.bad = self.f.remember("src", "Pump P1 is rated to 12 bar.", scope="team")
        self.summary = self.f.derive("sum", "P1 handles up to 12 bar.", parents=[self.bad],
                                     scope="team")
        self.unrelated = self.f.remember("src", "Pump P9 is blue.", scope="team")
        episode = self.f.start_episode("ops", "p1").id
        self.f.retrieve("ops", "pump P1 rated bar", episode_id=episode)
        self.f.cite("ops", episode, self.summary)
        gate = ActionGate(self.f, ActionPolicy(tools={"set": ToolRule("set")},
                                               grants={"ops": frozenset({"set"})}))
        assert gate.authorize("set", "ops", self.f.certify("set", [self.summary], "ops")).allowed
        self.f.quarantine(self.bad, reason="wrong rating", actor="op")

    def test_every_edge_type_is_recorded(self) -> None:
        kinds = {e.type for e in influence.edges(self.f)}
        for kind in ("summarized_from", "exposed_to", "relied_on", "authorized",
                     "invalidated_by"):
            self.assertIn(kind, kinds)
        self.assertTrue(kinds <= set(influence.EDGE_TYPES))

    def test_impact_keeps_the_three_sets_apart(self) -> None:
        report = influence.impact(self.f, self.bad)
        self.assertEqual(report["potentially_contaminated"]["memories"], [self.summary])
        self.assertIn("agent:ops", report["potentially_contaminated"]["agents"])
        retrieved = {r["memory"] for r in report["actually_retrieved"]}
        self.assertLessEqual(retrieved, {self.bad, self.summary})
        self.assertTrue(retrieved)
        self.assertEqual([r["memory"] for r in report["confirmed_use"]["relied_on"]],
                         [self.summary])
        self.assertEqual([a["memory"] for a in report["confirmed_use"]["authorized"]],
                         [self.summary])

    def test_an_unrelated_memory_is_not_contaminated(self) -> None:
        report = influence.impact(self.f, self.bad)
        self.assertNotIn(self.unrelated, report["potentially_contaminated"]["memories"])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
