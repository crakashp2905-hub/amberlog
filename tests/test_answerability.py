"""Answerability: a verdict on the evidence, separate from retrieval scores."""

from __future__ import annotations

import unittest

from amberlog import Amberlog
from amberlog.answerability import (ANSWERABLE, CONFLICTING, INSUFFICIENT, UNDETERMINED,
                                         assess, covers)


class Covers(unittest.TestCase):
    def test_same_unit_and_parameter(self) -> None:
        self.assertTrue(covers("What is the relief pressure of compressor K-31?",
                               "Compressor K-31: the relief pressure is 14 bar."))

    def test_transposed_identifier_is_not_cover(self) -> None:
        self.assertFalse(covers("What is the relief pressure of compressor K-31?",
                                "Compressor K-13: the relief pressure is 14 bar."))

    def test_other_parameter_of_the_right_unit_is_not_cover(self) -> None:
        self.assertFalse(covers("What is the relief pressure of compressor K-31?",
                                "Compressor K-31: the torque setting is 40 Nm."))

    def test_no_value_is_not_cover(self) -> None:
        self.assertFalse(covers("What is the relief pressure of compressor K-31?",
                                "Compressor K-31: relief pressure under review."))


class Verdicts(unittest.TestCase):
    def setUp(self) -> None:
        self.f = Amberlog(auto_activate=True, hold_suspicious=False)
        self.addCleanup(self.f.close)
        self.f.remember("ag_a", "Compressor K-31: the relief pressure is 14 bar.", scope="team")
        self.f.remember("ag_a", "Compressor K-13: the relief pressure is 22 bar.", scope="team")
        self.f.remember("ag_a", "Compressor K-31: the torque setting is 40 Nm.", scope="team")

    def ask(self, q: str):
        return self.f.retrieve("ag_reader", q, k=5).answerability(q)

    def test_answerable(self) -> None:
        a = self.ask("What is the relief pressure of compressor K-31?")
        self.assertEqual(a.verdict, ANSWERABLE)
        self.assertEqual(len(a.covering), 1)
        self.assertIsNotNone(a.retrieval_confidence)

    def test_neighbours_retrieved_but_insufficient(self) -> None:
        q = "What is the coolant flow of compressor K-31?"
        result = self.f.retrieve("ag_reader", q, k=5)
        self.assertGreater(len(result.exposed), 0, "retrieval still returns neighbours")
        self.assertEqual(result.answerability(q).verdict, INSUFFICIENT)
        self.assertTrue(result.answerability(q).should_abstain)

    def test_unknown_unit_is_insufficient(self) -> None:
        self.assertEqual(self.ask("What is the relief pressure of compressor K-77?").verdict,
                         INSUFFICIENT)

    def test_conflict_is_reported(self) -> None:
        self.f.remember("ag_b", "Compressor K-31: the relief pressure is 19 bar.", scope="team")
        self.assertEqual(self.ask("What is the relief pressure of compressor K-31?").verdict,
                         CONFLICTING)

    def test_no_identifier_is_undetermined_without_a_judge(self) -> None:
        self.assertEqual(self.ask("What is the usual relief pressure?").verdict, UNDETERMINED)

    def test_a_judge_decides_undetermined(self) -> None:
        q = "What is the usual relief pressure?"
        r = self.f.retrieve("ag_reader", q, k=5)
        self.assertEqual(r.answerability(q, judge=lambda q, ms: (False, "no")).verdict, INSUFFICIENT)
        self.assertEqual(r.answerability(q, judge=lambda q, ms: (True, "yes")).verdict, ANSWERABLE)

    def test_withdrawn_evidence_does_not_cover(self) -> None:
        mid = self.f.remember("ag_a", "Hoist H-14: the trip current is 30 A.", scope="team")
        self.f.quarantine(mid, reason="wrong", basis="contradicted")
        self.assertEqual(self.ask("What is the trip current of hoist H-14?").verdict, INSUFFICIENT)


class StandaloneAssess(unittest.TestCase):
    def test_empty_evidence(self) -> None:
        self.assertEqual(assess("What is the trip current of hoist H-14?", []).verdict, INSUFFICIENT)


if __name__ == "__main__":
    unittest.main()
