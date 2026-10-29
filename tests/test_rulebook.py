"""M2: a reflective rulebook adopts a revision only on held-out, verified evidence."""

from __future__ import annotations

import unittest

from amberlog import Amberlog
from amberlog.model import LifecycleState
from amberlog.objective import MemoryObjective, Rule
from amberlog.rulebook import Rulebook

DRAFTS_OUT = MemoryObjective("ignore drafts", exclude=(Rule("status", "eq", "draft"),))


class RulebookTests(unittest.TestCase):
    def setUp(self) -> None:
        self.f = Amberlog(":memory:", auto_activate=True)
        self.addCleanup(self.f.close)
        self.book = Rulebook(self.f, "night-shift", "agent", statement="start")

    def test_it_starts_empty_and_a_proposal_changes_nothing(self) -> None:
        self.assertEqual(self.book.current().include, ())
        candidate = self.book.propose(DRAFTS_OUT, "two answers came from drafts")
        self.assertEqual(self.book.current().exclude, ())
        self.assertIsNot(self.f.get(candidate).lifecycle_state, LifecycleState.ACTIVE)
        self.assertEqual(self.f.get(candidate).provenance.parents, ((self.book.memory_id, 1),))

    def test_better_held_out_evidence_adopts_it_with_the_reason_recorded(self) -> None:
        candidate = self.book.propose(DRAFTS_OUT, "drafts")
        decision = self.book.adopt(candidate, incumbent_score=0.5, candidate_score=0.75, n=16,
                                   verifier="env")
        self.assertTrue(decision.adopted)
        self.assertEqual(self.book.current().exclude, (Rule("status", "eq", "draft"),))
        self.assertEqual(self.book.version, 2)
        self.assertEqual([h["version"] for h in self.book.history()], [1, 2])
        self.assertIn("0.750 against 0.500", decision.reason)
        self.assertIs(self.f.get(candidate).lifecycle_state, LifecycleState.DEPRECATED)

    def test_worse_or_equal_evidence_keeps_the_incumbent(self) -> None:
        candidate = self.book.propose(DRAFTS_OUT, "drafts")
        decision = self.book.adopt(candidate, incumbent_score=0.6, candidate_score=0.6, n=16,
                                   verifier="env")
        self.assertFalse(decision.adopted)
        self.assertEqual(self.book.version, 1)
        self.assertIs(self.f.get(candidate).lifecycle_state, LifecycleState.DEPRECATED)

    def test_the_proposer_cannot_verify_its_own_rules(self) -> None:
        candidate = self.book.propose(DRAFTS_OUT, "drafts")
        with self.assertRaises(ValueError):
            self.book.adopt(candidate, incumbent_score=0.0, candidate_score=1.0, n=1,
                            verifier="agent")

    def test_a_rulebook_is_found_again_by_name(self) -> None:
        candidate = self.book.propose(DRAFTS_OUT, "drafts")
        self.book.adopt(candidate, incumbent_score=0.0, candidate_score=1.0, n=4, verifier="env")
        again = Rulebook(self.f, "night-shift", "agent")
        self.assertEqual(again.memory_id, self.book.memory_id)
        self.assertEqual(again.current().exclude, DRAFTS_OUT.exclude)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
