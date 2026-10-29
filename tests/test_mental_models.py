"""Evidence-backed mental models (plan Task 8).

Acceptance, from the plan: affected models become stale; unrelated models are
not needlessly refreshed; a stale model cannot satisfy a protected action's
checks. Plus: refresh jobs coalesce and are idempotent, and the registry
survives a restart because it is a projection of the log.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from amberlog import LifecycleState, Amberlog
from amberlog import mental_models as MM
from amberlog.actions import ActionGate, ActionPolicy, ToolRule


class Fixture(unittest.TestCase):
    def setUp(self) -> None:
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / "s.db"
        self.fabric = Amberlog(self.path, auto_activate=True)
        self.addCleanup(lambda: self.fabric.close())
        self.models = MM.MentalModels(self.fabric)
        f = self.fabric
        self.c1 = f.remember("ag1", "Crane 5 lifts 12 tonnes.")
        self.c2 = f.remember("ag2", "Crane 9 lifts 20 tonnes.")
        self.t1 = f.remember("ag3", "Tug 3 is in dry dock until May.")
        self.calls = 0
        self.models.define("cranes", "ag9", [self.c1, self.c2], self.summarize(
            [f.get(self.c1), f.get(self.c2)]))
        self.models.define("tugs", "ag9", [self.t1], self.summarize([f.get(self.t1)]))
        self.calls = 0

    def summarize(self, memories) -> str:
        self.calls += 1
        return "Summary: " + " ".join(m.content for m in memories)


class TestStaleness(Fixture):
    def test_new_models_are_fresh(self) -> None:
        self.assertEqual([self.models.status(m).state for m in ("cranes", "tugs")],
                         [MM.FRESH, MM.FRESH])

    def test_a_withdrawn_input_makes_only_its_models_stale(self) -> None:
        self.fabric.quarantine(self.c2, reason="load test failed", basis="contradicted")
        cranes = self.models.status("cranes")
        self.assertEqual(cranes.state, MM.STALE)
        self.assertEqual([(c.memory_id, c.reason) for c in cranes.changes],
                         [(self.c2, "withdrawn")])
        self.assertEqual(self.models.status("tugs").state, MM.FRESH)
        self.assertEqual(self.models.refresh_queue(), ["cranes"])

    def test_a_revised_input_makes_its_model_stale(self) -> None:
        self.fabric.revise(self.c1, "Crane 5 lifts 11 tonnes.", "ag1", "recalibrated")
        changes = self.models.status("cranes").changes
        self.assertEqual([(c.memory_id, c.reason) for c in changes], [(self.c1, "revised")])

    def test_the_watermark_is_recorded(self) -> None:
        self.assertIsInstance(self.models.status("cranes").watermark, int)


class TestRefresh(Fixture):
    def test_many_changes_coalesce_into_one_refresh(self) -> None:
        self.fabric.revise(self.c1, "Crane 5 lifts 11 tonnes.", "ag1", "recal")
        self.fabric.revise(self.c2, "Crane 9 lifts 19 tonnes.", "ag2", "recal")
        self.fabric.revise(self.c1, "Crane 5 lifts 10 tonnes.", "ag1", "recal again")
        results = self.models.refresh_all(self.summarize, "ag9")
        self.assertEqual([r.model_id for r in results], ["cranes"])
        self.assertEqual(self.calls, 1)
        status = self.models.status("cranes")
        self.assertEqual(status.state, MM.FRESH)
        content = self.fabric.get(status.memory_id).content
        self.assertIn("10 tonnes", content)
        self.assertIn("19 tonnes", content)

    def test_refresh_is_idempotent_and_never_touches_fresh_models(self) -> None:
        self.assertEqual(self.models.refresh_all(self.summarize, "ag9"), [])
        result = self.models.refresh("tugs", self.summarize, "ag9")
        self.assertFalse(result.refreshed)
        self.assertEqual(self.calls, 0)

    def test_a_withdrawn_input_is_left_out_of_the_refresh(self) -> None:
        self.fabric.quarantine(self.c2, reason="wrong", basis="contradicted")
        result = self.models.refresh("cranes", self.summarize, "ag9")
        self.assertTrue(result.refreshed)
        new = self.fabric.get(result.memory_id)
        self.assertNotIn("Crane 9", new.content)
        self.assertEqual([p for p, _ in new.provenance.parents], [self.c1])
        # The superseded version is deprecated, not deleted.
        self.assertIs(self.fabric.get(result.superseded).lifecycle_state,
                      LifecycleState.DEPRECATED)

    def test_with_no_usable_input_the_model_is_not_rewritten(self) -> None:
        self.fabric.quarantine(self.t1, reason="wrong", basis="contradicted")
        result = self.models.refresh("tugs", self.summarize, "ag9")
        self.assertEqual((result.refreshed, result.state), (False, MM.INSUFFICIENT))
        self.assertEqual(self.models.status("tugs").state, MM.STALE)

    def test_an_unreviewed_refresh_is_pending_not_requeued(self) -> None:
        fabric = Amberlog()  # no auto-activation: writes need review
        self.addCleanup(fabric.close)
        models = MM.MentalModels(fabric)
        fact = fabric.remember("ag", "Hoist 6 is rated 2 tonnes.")
        fabric.validate(fact, actor="sup")
        models.define("hoists", "ag9", [fact], "Hoists: 2 t")
        self.assertEqual(models.status("hoists").state, MM.PENDING_REVIEW)
        self.assertEqual(models.refresh_queue(), [])


class TestProtectedAction(Fixture):
    def test_a_stale_model_cannot_satisfy_a_protected_action(self) -> None:
        gate = ActionGate(self.fabric, ActionPolicy(
            tools={"plan_lift": ToolRule("plan_lift")},
            grants={"ag9": frozenset({"plan_lift"})}))
        model = self.models.status("cranes").memory_id
        cert = self.fabric.certify("lift", [model], "ag9")
        self.assertTrue(gate.authorize("plan_lift", "ag9", cert).allowed)
        self.fabric.quarantine(self.c2, reason="load test failed", basis="contradicted")
        decision = gate.authorize("plan_lift", "ag9", cert)
        self.assertFalse(decision.allowed)
        # And a fresh certificate on the stale model is refused too.
        again = self.fabric.certify("lift", [model], "ag9")
        self.assertFalse(gate.authorize("plan_lift", "ag9", again).allowed)


class TestDurability(Fixture):
    def test_the_registry_survives_a_restart(self) -> None:
        self.fabric.quarantine(self.c2, reason="wrong", basis="contradicted")
        self.fabric.close()
        self.fabric = Amberlog(self.path, auto_activate=True)
        models = MM.MentalModels(self.fabric)
        self.assertEqual(models.model_ids(), ["cranes", "tugs"])
        self.assertEqual(models.refresh_queue(), ["cranes"])


if __name__ == "__main__":
    unittest.main()
