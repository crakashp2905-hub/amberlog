"""Incident reconstruction (plan Task 9).

Acceptance, from the plan: a known synthetic incident path can be
reconstructed; false attribution is measured (experiments/p9_incidents.py);
dependency is not reported as proof of causation.
"""

from __future__ import annotations

import json
import unittest

from memory_fabric import MemoryFabric
from memory_fabric.actions import ActionGate, ActionPolicy, ToolRule
from memory_fabric.incident import CAVEAT, reconstruct, responsible_sources
from memory_fabric.justification import JustificationKind, justification_context

POISON = "Crane 9 rated for 30 tonnes per the bulletin."
HONEST = "Crane 9 load test held 20 tonnes at the yard."


class KnownIncident(unittest.TestCase):
    """mallory's false rating and an honest test both feed a lift plan; the
    plan is certified and acted on; mallory is found out afterwards."""

    def setUp(self) -> None:
        f = self.fabric = MemoryFabric(auto_activate=True, seed=0)
        self.addCleanup(f.close)
        self.poison = f.remember("mallory", POISON)
        self.honest = f.remember("ana", HONEST)
        self.decoy = f.remember("eve", "Canteen reopens at 6.")
        self.rating = f.derive("ben", "Crane 9 rating summary", parents=[self.poison],
                               context=justification_context(
                                   [(self.poison, JustificationKind.REQUIRED)]))
        self.plan = f.derive("cho", "Lift plan for crane 9",
                             parents=[self.rating, self.honest],
                             context=justification_context([
                                 (self.rating, JustificationKind.REQUIRED),
                                 (self.honest, JustificationKind.REQUIRED)]))
        f.retrieve("actor", "crane 9 lift plan canteen", k=5)
        gate = ActionGate(f, ActionPolicy(tools={"lift": ToolRule("lift")},
                                          grants={"actor": frozenset({"lift"})}))
        self.decision = gate.authorize("lift", "actor", f.certify("lift-1", [self.plan], "actor"))
        f.quarantine(self.poison, reason="forged bulletin", basis="contradicted")
        self.report = reconstruct(f)

    def test_the_action_was_taken(self) -> None:
        self.assertTrue(self.decision.allowed)
        self.assertTrue(self.report.allowed)

    def test_the_full_path_is_reconstructed(self) -> None:
        self.assertEqual({n.memory_id for n in self.report.nodes},
                         {self.plan, self.rating, self.poison, self.honest})
        self.assertIn((self.plan, self.rating, "required"), self.report.edges)
        self.assertIn((self.rating, self.poison, "required"), self.report.edges)

    def test_writers_are_named_and_decoys_are_not_on_the_path(self) -> None:
        writers = {n.memory_id: n.writer for n in self.report.nodes}
        self.assertEqual(writers[self.poison], "mallory")
        self.assertNotIn(self.decoy, writers)

    def test_state_is_as_of_the_action_and_later_withdrawals_are_listed_apart(self) -> None:
        at_action = {n.memory_id: n.lifecycle_at_action for n in self.report.nodes}
        self.assertEqual(at_action[self.poison], "active")
        later = {(x["memory_id"], x["to"]) for x in self.report.found_later}
        self.assertIn((self.poison, "quarantined"), later)

    def test_both_sources_of_a_conjunction_are_necessary(self) -> None:
        self.assertEqual(set(responsible_sources(self.report)), {self.poison, self.honest})

    def test_the_exposure_to_the_acting_agent_is_recorded(self) -> None:
        exposed = {x["memory_id"] for x in self.report.exposures}
        self.assertTrue(exposed & {self.plan, self.rating, self.honest, self.poison})

    def test_the_report_carries_no_content(self) -> None:
        dump = json.dumps(self.report.to_json(), default=str)
        for text in (POISON, HONEST, "Lift plan", "rating summary", "Canteen"):
            self.assertNotIn(text, dump)

    def test_dependency_is_never_called_cause(self) -> None:
        self.assertIn("not proof of causation", CAVEAT)
        self.assertEqual(self.report.to_json()["caveat"], CAVEAT)
        self.assertNotIn("cause", json.dumps(
            [s.__dict__ for s in self.report.sources]).lower())

    def test_reconstruction_does_not_write(self) -> None:
        head = self.fabric.log.head_seq
        reconstruct(self.fabric)
        self.assertEqual(self.fabric.log.head_seq, head)


class AlternativeSupport(unittest.TestCase):
    def test_an_independently_corroborated_source_is_not_necessary(self) -> None:
        f = MemoryFabric(auto_activate=True)
        self.addCleanup(f.close)
        a = f.remember("ana", "Tug 3 overheated at 40C in July.")
        b = f.remember("ben", "Tug 3 engine log shows 41C in August.")
        c = f.derive("cho", "Tug 3 runs hot.", parents=[a, b], context=justification_context(
            [(a, JustificationKind.ALTERNATIVE), (b, JustificationKind.ALTERNATIVE)]))
        gate = ActionGate(f, ActionPolicy(tools={"t": ToolRule("t")},
                                          grants={"x": frozenset({"t"})}))
        gate.authorize("t", "x", f.certify("c", [c], "x"))
        self.assertEqual(responsible_sources(reconstruct(f)), [])

    def test_no_action_is_a_lookup_error(self) -> None:
        f = MemoryFabric()
        self.addCleanup(f.close)
        with self.assertRaises(LookupError):
            reconstruct(f)


if __name__ == "__main__":
    unittest.main()
