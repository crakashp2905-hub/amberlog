"""The review queue and its four decisions, each recorded with its reviewer."""

from __future__ import annotations

import unittest

from amberlog import Amberlog
from amberlog.model import LifecycleState, Scope
from amberlog.review import ReviewError, decide, queue
from amberlog.status import labels


class Queue(unittest.TestCase):
    def setUp(self) -> None:
        self.fabric = Amberlog(":memory:")
        self.addCleanup(self.fabric.close)

    def test_candidates_wait_oldest_first_and_active_ones_do_not(self) -> None:
        first = self.fabric.remember("ana", "pump 3 needs a new seal")
        second = self.fabric.remember("ben", "valve 7 stuck open")
        active = self.fabric.remember("cho", "yard opens at 6", auto_activate=True)
        ids = [i.memory_id for i in queue(self.fabric)]
        self.assertEqual(ids, [first, second])
        self.assertNotIn(active, ids)

    def test_a_screen_quarantine_waits_and_its_secret_is_not_shown(self) -> None:
        key = "AKIA" + "QWER" * 4
        mid = self.fabric.remember("ana", f"deploy with key {key}")
        item = next(i for i in queue(self.fabric) if i.memory_id == mid)
        self.assertEqual(item.kind, "screened")
        self.assertNotIn(key, item.content)
        self.assertIn("--override-screen", item.commands["approve"])


class Decisions(unittest.TestCase):
    def setUp(self) -> None:
        self.fabric = Amberlog(":memory:")
        self.addCleanup(self.fabric.close)
        self.mid = self.fabric.remember("ana", "pump 3 needs a new seal")

    def memory(self):
        return self.fabric.state.memories[self.mid]

    def test_approve_makes_it_usable_by_the_team_and_names_the_reviewer(self) -> None:
        decide(self.fabric, self.mid, "approve", reviewer="carol")
        self.assertIs(self.memory().lifecycle_state, LifecycleState.ACTIVE)
        self.assertIs(self.memory().scope, Scope.TEAM)
        reviewed = {l.key: l for l in labels(self.fabric, self.mid)}["reviewed"]
        self.assertTrue(reviewed.established)
        self.assertIn("carol", reviewed.detail)

    def test_limit_keeps_it_with_its_author(self) -> None:
        decide(self.fabric, self.mid, "limit", reviewer="carol")
        self.assertIs(self.memory().lifecycle_state, LifecycleState.ACTIVE)
        self.assertIs(self.memory().scope, Scope.PRIVATE)
        self.assertEqual([m.id for m in self.fabric.retrieve("ben", "pump 3 seal").exposed], [])

    def test_correct_revises_then_approves(self) -> None:
        decide(self.fabric, self.mid, "correct", reviewer="carol",
               correction="pump 3 needs a new seal kit, part 44-B")
        self.assertEqual(self.memory().version, 2)
        self.assertIn("44-B", self.memory().content)
        self.assertIs(self.memory().lifecycle_state, LifecycleState.ACTIVE)
        self.assertIs(self.memory().scope, Scope.TEAM)

    def test_reject_needs_a_reason_and_keeps_the_record(self) -> None:
        with self.assertRaises(ReviewError):
            decide(self.fabric, self.mid, "reject", reviewer="carol")
        decide(self.fabric, self.mid, "reject", reviewer="carol", reason="duplicate")
        self.assertIs(self.memory().lifecycle_state, LifecycleState.DEPRECATED)
        self.assertEqual(queue(self.fabric), [])

    def test_a_decision_needs_a_named_reviewer(self) -> None:
        for anonymous in ("", "operator"):
            with self.subTest(reviewer=anonymous), self.assertRaises(ReviewError):
                decide(self.fabric, self.mid, "approve", reviewer=anonymous)

    def test_something_already_decided_is_not_decided_again(self) -> None:
        decide(self.fabric, self.mid, "approve", reviewer="carol")
        with self.assertRaises(ReviewError):
            decide(self.fabric, self.mid, "reject", reviewer="dan", reason="changed my mind")

    def test_a_screened_memory_needs_an_explicit_override(self) -> None:
        mid = self.fabric.remember("ana", "deploy with key " + "AKIA" + "QWER" * 4)
        with self.assertRaises(ReviewError):
            decide(self.fabric, mid, "approve", reviewer="carol")
        decide(self.fabric, mid, "limit", reviewer="carol", override_screen=True)
        self.assertIs(self.fabric.state.memories[mid].lifecycle_state, LifecycleState.ACTIVE)


class TheDashboardShowsTheQueue(unittest.TestCase):
    def test_the_review_route_lists_it_and_writes_nothing(self) -> None:
        from amberlog.observability.server import Api

        fabric = Amberlog(":memory:")
        self.addCleanup(fabric.close)
        mid = fabric.remember("ana", "pump 3 needs a new seal")
        before = fabric.log.head_seq
        items = Api(fabric).handle("/api/review", {})
        self.assertEqual([i["memory_id"] for i in items], [mid])
        self.assertEqual(fabric.log.head_seq, before)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
