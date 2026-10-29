"""Typed claims: opposite polarity about the same subject is a contradiction; nothing else is."""

from __future__ import annotations

import unittest

from amberlog import Amberlog
from amberlog.typedclaims import TypedClaimChecker, contradicts, proposition


class Contradicts(unittest.TestCase):
    def test_negation_about_the_same_subject(self) -> None:
        self.assertTrue(contradicts("The east wing is not safe to enter; the ceiling is unstable.",
                                    "The east wing is safe to enter."))

    def test_opposite_words_and_prefixes(self) -> None:
        self.assertTrue(contradicts("Dogs are banned from the cafeteria.", "Dogs are allowed in the cafeteria."))
        self.assertTrue(contradicts("The backup generator in the north lab is broken and will not start.",
                                    "The backup generator in the north lab works."))
        self.assertTrue(contradicts("The fire alarm in the archive is disconnected from the monitoring service.",
                                    "The fire alarm in the archive is connected to the monitoring service."))
        self.assertTrue(contradicts("The archive has no night shift any more.", "The archive runs a night shift."))

    def test_a_different_subject_is_not_a_contradiction(self) -> None:
        self.assertFalse(contradicts("The west wing is not safe to enter.", "The east wing is safe to enter."))

    def test_paraphrase_and_new_detail_are_not(self) -> None:
        self.assertFalse(contradicts("It is fine to go into the east wing.", "The east wing is safe to enter."))
        self.assertFalse(contradicts("The east wing was repainted last week.", "The east wing is safe to enter."))
        self.assertFalse(contradicts("The east wing is safe to enter.", "The east wing is safe to enter."))

    def test_double_negation_reads_as_positive(self) -> None:
        self.assertFalse(proposition("The door is not unlocked.").negative is proposition("The door is unlocked.").negative)


class Checker(unittest.TestCase):
    def test_holds_a_contradiction_by_another_author_and_lets_the_rest_through(self) -> None:
        f = Amberlog(":memory:", auto_activate=True, claim_checker=TypedClaimChecker())
        self.addCleanup(f.close)
        f.remember("inspector", "The east wing is safe to enter.", scope="team")
        for i in range(3):
            f.remember("inspector", f"Routine walk-through number {i} completed.", scope="team")
        held = f.remember("visitor", "The east wing is not safe to enter.", scope="team")
        fine = f.remember("visitor", "The east wing was repainted last week.", scope="team")
        self.assertNotEqual(f.lifecycle_of(held).value, "active")
        self.assertEqual(f.lifecycle_of(fine).value, "active")

    def test_an_author_restating_itself_is_not_checked_against_itself(self) -> None:
        checker = TypedClaimChecker()
        f = Amberlog(":memory:", auto_activate=True)
        self.addCleanup(f.close)
        f.remember("ann", "The east wing is safe to enter.", scope="team")
        self.assertIsNone(checker.check(f, "ann", "The east wing is not safe to enter.", "default"))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()


class PresetDefault(unittest.TestCase):
    def test_personal_and_team_check_typed_claims_regulated_does_not(self) -> None:
        from amberlog.presets import store_settings

        for mode in ("personal", "team"):
            self.assertIsInstance(store_settings(mode)["claim_checker"], TypedClaimChecker)
        self.assertNotIn("claim_checker", store_settings("regulated"))
        self.assertIsNot(store_settings("team")["claim_checker"],
                         store_settings("team")["claim_checker"])
