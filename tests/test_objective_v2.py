"""MemoryObjectiveV2: hard vs soft, safety evidence kept, evidence-aware ranking, governed change."""

from __future__ import annotations

import unittest

from memory_fabric import MemoryFabric
from memory_fabric.events import EventType
from memory_fabric.objective import MemoryObjective, Rule
from memory_fabric.objective_v2 import Constraint, MemoryObjectiveV2, ObjectiveLog, from_v1


def site(value: str) -> Rule:
    return Rule("site", "eq", value)


class Fixture(unittest.TestCase):
    def setUp(self) -> None:
        self.f = MemoryFabric(":memory:", auto_activate=True)
        self.addCleanup(self.f.close)
        r = self.f.remember
        self.north = r("tech", "Pump P1 purge time at North is 30 s.", context={"site": "north"},
                       scope="team")
        self.south = r("tech", "Pump P1 purge time at South is 45 s.", context={"site": "south"},
                       scope="team")
        self.hazard = r("safety", "Pump P1 purge must never be skipped at any site: H2 build-up.",
                        context={"site": "south", "safety": True}, scope="team")
        self.vendor = r("agent", "Vendor says pump P1 purge time is 10 s.",
                        context={"site": "north", "origin": "web:vendor"}, scope="team")

    def shown(self, objective: object) -> list[str]:
        return [m.id for m in self.f.retrieve("ops", "pump P1 purge time", k=4,
                                              objective=objective).exposed]


class HardSoftUncertain(Fixture):
    def test_a_hard_exclusion_filters_but_keeps_unreviewed_safety_evidence(self) -> None:
        obj = MemoryObjectiveV2("purge at North", excluded_context=(Constraint(site("south")),),
                                compiled_by="model")
        shown = self.shown(obj)
        self.assertNotIn(self.south, shown)
        self.assertIn(self.hazard, shown, "safety evidence survives an unreviewed exclusion")
        why = {e["memory_id"]: e["reason"] for e in obj.explain(self.f, [self.hazard])}
        self.assertIn("kept: safety evidence", why[self.hazard])

    def test_only_a_reviewed_objective_excludes_safety_evidence(self) -> None:
        obj = MemoryObjectiveV2("purge at North", excluded_context=(Constraint(site("south")),),
                                compiled_by="model").reviewed("lead")
        self.assertNotIn(self.hazard, self.shown(obj))

    def test_the_compiler_cannot_review_its_own_objective(self) -> None:
        with self.assertRaises(ValueError):
            MemoryObjectiveV2("x", compiled_by="model").reviewed("model")

    def test_soft_and_uncertain_rules_never_filter(self) -> None:
        for strength in ("soft", "uncertain"):
            obj = MemoryObjectiveV2("purge", excluded_context=(Constraint(site("south"), strength),))
            self.assertIn(self.south, self.shown(obj), strength)

    def test_a_soft_preference_moves_rank(self) -> None:
        north_first = MemoryObjectiveV2("purge", preferred_evidence=(
            Constraint(site("north"), "soft", 1.0),))
        south_first = MemoryObjectiveV2("purge", preferred_evidence=(
            Constraint(site("south"), "soft", 1.0),))
        a, b = self.shown(north_first), self.shown(south_first)
        self.assertLess(a.index(self.north), a.index(self.south))
        self.assertLess(b.index(self.south), b.index(self.north))

    def test_a_compiled_v1_objective_becomes_uncertain(self) -> None:
        v1 = MemoryObjective("north only", include=((site("north"),),), exclude=(site("south"),))
        v2 = from_v1(v1, compiled_by="model")
        self.assertTrue(all(c.strength == "uncertain" for c in v2.excluded_context))
        self.assertIn(self.south, self.shown(v2))


class EvidenceAware(Fixture):
    def test_untrusted_evidence_ranks_below_and_is_dropped_at_high_impact(self) -> None:
        low = MemoryObjectiveV2("purge at North", scope=((site("north"),),))
        shown = self.shown(low)
        self.assertLess(shown.index(self.north), shown.index(self.vendor))
        high = MemoryObjectiveV2("purge at North", scope=((site("north"),),),
                                 decision_impact="high")
        self.assertNotIn(self.vendor, self.shown(high))

    def test_expired_validity_is_hidden_unless_history_is_asked_for(self) -> None:
        old = self.f.remember("tech", "Pump P1 purge time at North was 20 s.",
                              context={"site": "north"}, scope="team", valid_to=1)
        self.assertNotIn(old, self.shown(MemoryObjectiveV2("purge", scope=((site("north"),),))))
        shown = self.shown(MemoryObjectiveV2("purge", scope=((site("north"),),),
                                             include_history=True))
        self.assertEqual(shown[-1], old)

    def test_required_fact_omission_is_reported(self) -> None:
        obj = MemoryObjectiveV2("purge", required_facts=("30 s", "H2"),
                                excluded_context=(Constraint(site("south")),)).reviewed("lead")
        contents = [self.f.get(m).content for m in self.shown(obj)]
        self.assertEqual(obj.omissions(contents), ["H2"])


class IrrelevantIsNotDeletable(Fixture):
    def test_applying_an_objective_changes_no_lifecycle(self) -> None:
        before = len(list(self.f.log.read_types([EventType.LIFECYCLE_CHANGED])))
        self.shown(MemoryObjectiveV2("x", excluded_context=(Constraint(site("south")),),
                                     scope=((site("north"),),)).reviewed("lead"))
        self.assertEqual(len(list(self.f.log.read_types([EventType.LIFECYCLE_CHANGED]))), before)
        self.assertEqual(self.f.get(self.south).lifecycle_state.value, "active")


class GovernedChange(Fixture):
    def test_a_proposal_needs_another_reviewer_and_no_regression(self) -> None:
        log = ObjectiveLog(self.f)
        obj = MemoryObjectiveV2("purge at North", scope=((site("north"),),))
        digest = log.propose(obj, proposer="agent", evaluation={"accuracy": 0.9},
                             reason="fewer cross-site errors in eval")
        with self.assertRaises(ValueError):
            log.adopt(digest, reviewer="agent", baseline={"accuracy": 0.8})
        worse = log.propose(obj.reviewed("x"), proposer="agent", evaluation={"accuracy": 0.7},
                            reason="r")
        with self.assertRaises(ValueError):
            log.adopt(worse, reviewer="lead", baseline={"accuracy": 0.8})
        adopted = log.adopt(digest, reviewer="lead", baseline={"accuracy": 0.8})
        self.assertEqual(adopted.digest(), digest)
        self.assertEqual([e.payload["status"] for e in log.events()],
                         ["proposed", "proposed", "rejected", "adopted"])

    def test_round_trip(self) -> None:
        obj = MemoryObjectiveV2("g", required_facts=("a",), preferred_evidence=(
            Constraint(site("n"), "soft", 0.3),), safety_constraints=(Rule("kind", "eq", "h"),),
            scope=((site("n"),),), freshness_ms=5, decision_impact="high")
        self.assertEqual(MemoryObjectiveV2.from_json(obj.to_json()), obj)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
