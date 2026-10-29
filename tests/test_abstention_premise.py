"""Known-answer tests for the abstention-premise estimators.

These exist because of a specific, measured failure.
`research/results/abstention-signals.md` reported a pooled **AUC of 0.319** for
its one real signal — *below* chance, "with the effect reversed" — and built a
title, a summary table and two sections of narrative on it. The true value is
**0.682**: the published number was the probability that an *unanswerable*
instance outscores an answerable one, reported as though it were the detector's
discrimination. Every other figure in that result reproduced exactly.

A sign error in a summary statistic is invisible on inspection and fatal to the
conclusion, and AGENTS.md requires estimators to carry known-answer tests. So
`auc()` is pinned against cases whose answers are arithmetic rather than
empirical — above all **the direction**, which is the thing that was wrong.
"""

from __future__ import annotations

import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from experiments.x1_abstention_premise import (  # noqa: E402
    auc, best_f1, cohens_d, content_terms, turns_of,
)


class TestAUCDirection(unittest.TestCase):
    """`auc(positive, negative)` is P(a negative outscores a positive), where
    `positive` is the unanswerable group. A detector that abstains on low
    scores wants this **above** 0.5."""

    def test_perfect_separation_in_the_expected_direction_is_one(self):
        """Unanswerable scoring strictly lower is the signal working, and it
        must read 1.0 rather than 0.0. This is the assertion whose absence
        cost abstention-signals.md its headline."""
        self.assertEqual(auc([0.1, 0.2, 0.3], [0.7, 0.8, 0.9]), 1.0)

    def test_perfect_separation_the_wrong_way_is_zero(self):
        self.assertEqual(auc([0.7, 0.8, 0.9], [0.1, 0.2, 0.3]), 0.0)

    def test_a_published_value_and_its_complement_are_distinguishable(self):
        """The two numbers the correction is about, on one fixture."""
        unanswerable = [0.1, 0.2, 0.3, 0.4]
        answerable = [0.25, 0.35, 0.45, 0.55]
        forward = auc(unanswerable, answerable)
        backward = auc(answerable, unanswerable)
        self.assertAlmostEqual(forward + backward, 1.0)
        self.assertGreater(forward, 0.5)
        self.assertLess(backward, 0.5)

    def test_identical_distributions_are_a_coin_flip(self):
        self.assertEqual(auc([1.0, 2.0], [1.0, 2.0]), 0.5)

    def test_ties_count_as_half(self):
        self.assertEqual(auc([1.0], [1.0]), 0.5)
        self.assertEqual(auc([1.0, 1.0], [1.0, 2.0]), 0.75)

    def test_an_empty_group_is_none_rather_than_a_number(self):
        self.assertIsNone(auc([], [1.0]))
        self.assertIsNone(auc([1.0], []))


class TestBestF1(unittest.TestCase):
    def test_perfect_separation_scores_one_with_no_false_positives(self):
        best = best_f1([0.1, 0.2], [0.8, 0.9])
        self.assertEqual(best["f1"], 1.0)
        self.assertEqual(best["recall_tpr"], 1.0)
        self.assertEqual(best["fpr"], 0.0)

    def test_the_reported_point_is_arithmetically_consistent(self):
        """TPR, FPR and precision must describe one threshold. The published
        result's F1, TPR, FPR and precision did agree with each other — only
        its AUC did not — so consistency among these four is necessary and not
        sufficient, and it is still worth pinning."""
        positive = [0.1, 0.2, 0.3, 0.4, 0.5]
        negative = [0.15, 0.25, 0.6, 0.7, 0.8]
        best = best_f1(positive, negative)
        caught = sum(1 for p in positive if p <= best["threshold"])
        wrong = sum(1 for n in negative if n <= best["threshold"])
        self.assertAlmostEqual(best["recall_tpr"], caught / len(positive), 4)
        self.assertAlmostEqual(best["fpr"], wrong / len(negative), 4)
        self.assertAlmostEqual(best["precision"], caught / (caught + wrong), 4)

    def test_a_signal_with_no_information_still_returns_a_point(self):
        """A detector that abstains on everything gets recall 1.0 at the base
        rate, which is exactly what section 1 of the result measured for the
        term-absence family. It is a number, not an error."""
        best = best_f1([0.5] * 3, [0.5] * 7)
        self.assertEqual(best["recall_tpr"], 1.0)
        self.assertAlmostEqual(best["precision"], 0.3)


class TestCohensD(unittest.TestCase):
    def test_a_known_value(self):
        """Means 1 apart, both variances 1 (sample variance of this set is
        exactly 1), so d = -1 with the lower group first."""
        self.assertAlmostEqual(cohens_d([0.0, 1.0, 2.0], [1.0, 2.0, 3.0]),
                               -1.0, places=6)

    def test_no_variance_is_none_rather_than_a_division_by_zero(self):
        self.assertIsNone(cohens_d([1.0, 1.0], [1.0, 1.0]))

    def test_one_value_is_none(self):
        self.assertIsNone(cohens_d([1.0], [1.0, 2.0]))


class TestTextHelpers(unittest.TestCase):
    def test_content_terms_drops_the_products_stopwords(self):
        terms = content_terms("What is the pressure for the crane?")
        self.assertIn("pressure", terms)
        self.assertIn("crane", terms)
        self.assertNotIn("the", terms)
        self.assertNotIn("what", terms)

    def test_single_characters_are_dropped(self):
        self.assertNotIn("x", content_terms("a x pressure"))

    def test_turns_are_read_from_either_shape(self):
        """Haystacks hold dicts with `content`; a plain string is tolerated
        rather than crashing a 500-instance run on one malformed session."""
        instance = {"haystack_sessions": [
            [{"content": "first"}, {"content": "  "}],
            ["second"],
            None,
        ]}
        self.assertEqual(turns_of(instance), ["first", "second"])

    def test_a_missing_haystack_is_empty_rather_than_an_error(self):
        self.assertEqual(turns_of({}), [])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
