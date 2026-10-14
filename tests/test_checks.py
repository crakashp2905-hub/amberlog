"""The runtime checks, tested against the errors they were built from.

Each test reconstructs an actual published mistake and asserts the check
catches it. That is the only standard that matters here: a check that passes
on invented data and would have passed on the real fault is decoration.
"""

from __future__ import annotations

import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from experiments import checks  # noqa: E402


class TestDirection(unittest.TestCase):
    """The complement error: `abstention-signals.md` reported 0.319 for a
    signal whose value is 0.682."""

    def test_both_orientations_are_reported(self):
        out = checks.direction([0.1, 0.2, 0.3], [0.7, 0.8, 0.9])
        self.assertEqual(out["auc"], 1.0)
        self.assertEqual(out["auc_if_reversed"], 0.0)

    def test_the_two_orientations_sum_to_one(self):
        out = checks.direction([0.1, 0.4, 0.5], [0.2, 0.6, 0.7])
        self.assertAlmostEqual(out["auc"] + out["auc_if_reversed"], 1.0)

    def test_the_claimed_convention_is_recorded(self):
        """So the output states an intention rather than an artefact."""
        a = checks.direction([0.1], [0.9], expect="negative_scores_higher")
        b = checks.direction([0.1], [0.9], expect="positive_scores_higher")
        self.assertEqual(a["auc"], 1.0)
        self.assertEqual(b["auc"], 0.0)

    def test_above_chance_is_stated_not_inferred(self):
        self.assertTrue(checks.direction([0.1], [0.9])["above_chance"])
        self.assertFalse(checks.direction([0.9], [0.1])["above_chance"])

    def test_an_empty_group_does_not_invent_a_direction(self):
        out = checks.direction([], [0.5])
        self.assertIsNone(out["auc"])
        self.assertTrue(out["ok"])

    def test_the_shared_auc_matches_the_published_pair(self):
        """0.319 and 0.681 are complements; one implementation means the
        convention is chosen once rather than per experiment."""
        positive, negative = [0.310] * 3, [0.456] * 7
        self.assertAlmostEqual(checks.auc(positive, negative), 1.0)
        self.assertAlmostEqual(checks.auc(negative, positive), 0.0)


class TestCeiling(unittest.TestCase):
    """Principle 8b. Phase A's oracle was bounded by its retrieval budget and
    looked unimpeachable until an arm beat it."""

    def test_an_arm_above_the_oracle_fails(self):
        out = checks.ceiling(
            {"arm": {"f1": 0.9}, "oracle": {"f1": 0.8}}, "f1")
        self.assertFalse(out["ok"])
        self.assertEqual(out["arms_above_ceiling"], {"arm": 0.9})
        self.assertIn("ceiling is wrong", out["note"])

    def test_an_arm_equal_to_the_oracle_is_allowed(self):
        """Matching the ceiling is the best possible result, not a fault."""
        self.assertTrue(checks.ceiling(
            {"arm": {"f1": 0.8}, "oracle": {"f1": 0.8}}, "f1")["ok"])

    def test_a_missing_oracle_is_reported_rather_than_assumed_fine(self):
        out = checks.ceiling({"arm": {"f1": 0.9}}, "f1")
        self.assertTrue(out["ok"])
        self.assertIn("no 'oracle' arm", out["note"])

    def test_an_arm_without_the_metric_is_skipped(self):
        out = checks.ceiling(
            {"a": {}, "b": {"f1": 0.5}, "oracle": {"f1": 0.8}}, "f1")
        self.assertTrue(out["ok"])


class TestBaselineMax(unittest.TestCase):
    """Principle 8c, reconstructed from P2: `full_context` reached the
    oracle's 0.800, so the threshold was unreachable before any method."""

    def test_p2s_degenerate_metric_is_caught(self):
        out = checks.baseline_max(
            {"full_context": {"suff": 0.800}, "oracle": {"suff": 0.800}},
            "suff", ["full_context"])
        self.assertFalse(out["ok"])
        self.assertEqual(out["headroom"], 0.0)
        self.assertIn("principle 8c", out["note"])

    def test_x1s_implied_by_default_is_caught(self):
        """The family whose baseline reached 1.000 on the registered metric
        while the registration recorded B = 0.000 from another table."""
        out = checks.baseline_max(
            {"lexical": {"suff": 1.0}, "oracle": {"suff": 1.0}},
            "suff", ["lexical"])
        self.assertFalse(out["ok"])

    def test_real_headroom_passes_and_is_reported(self):
        out = checks.baseline_max(
            {"lexical": {"suff": 0.0}, "oracle": {"suff": 1.0}},
            "suff", ["lexical"])
        self.assertTrue(out["ok"])
        self.assertEqual(out["B_best_baseline"], 0.0)
        self.assertEqual(out["headroom"], 1.0)

    def test_the_strongest_baseline_is_the_one_that_counts(self):
        """B is a max over baselines, not whichever was listed first: a
        registration that bounds itself by its weakest baseline has set no
        bound at all."""
        out = checks.baseline_max(
            {"weak": {"suff": 0.1}, "strong": {"suff": 0.9},
             "oracle": {"suff": 1.0}}, "suff", ["weak", "strong"])
        self.assertEqual(out["B_best_baseline"], 0.9)
        self.assertEqual(out["headroom"], 0.1)
        # 0.1 of headroom is thin but above the 0.05 abandonment tolerance, so
        # this passes. The check reports the number; the registration decides
        # whether 0.1 is worth a threshold.
        self.assertTrue(out["ok"])

    def test_headroom_at_the_tolerance_is_degenerate(self):
        out = checks.baseline_max(
            {"b": {"suff": 0.95}, "oracle": {"suff": 1.0}}, "suff", ["b"])
        self.assertEqual(out["headroom"], 0.05)
        self.assertFalse(out["ok"])

    def test_a_baseline_not_present_in_the_run_is_not_counted(self):
        """A registered baseline that never ran cannot bound anything, and
        silently treating it as 0.0 would invent headroom."""
        out = checks.baseline_max(
            {"oracle": {"suff": 1.0}}, "suff", ["never_ran"])
        self.assertTrue(out["ok"])
        self.assertIn("no registered baseline", out["note"])


class TestClassCollapse(unittest.TestCase):
    """A failed parse scored 17/17 on the column built to catch failure."""

    def test_a_classifier_with_no_failure_class_fails(self):
        out = checks.class_collapse({"plain": 17, "modifier": 1, "default": 1})
        self.assertFalse(out["ok"])
        self.assertIn("indistinguishable", out["note"])

    def test_counting_unparsed_passes(self):
        out = checks.class_collapse(
            {"plain": 9, "modifier": 1, "unparsed": 9}, majority_class="plain")
        self.assertTrue(out["ok"])
        self.assertEqual(out["failures"], {"unparsed": 9})

    def test_a_zero_count_still_counts_as_counted(self):
        """Reporting `unparsed: 0` is the evidence that nothing failed;
        omitting the field is the evidence of nothing."""
        self.assertTrue(checks.class_collapse(
            {"plain": 17, "unparsed": 0})["ok"])


class TestCollapsedToPrior(unittest.TestCase):
    """A Platt refit of Kev-0.8B reached ECE 0.0083 by predicting the base
    rate: perfectly calibrated and perfectly useless."""

    def test_the_real_collapse_is_caught(self):
        out = checks.collapsed_to_prior(
            mean_probability=0.94, base_rate=0.94, accuracy_at_half=0.94)
        self.assertFalse(out["ok"])
        self.assertIn("predicts the base rate", out["note"])

    def test_a_predictor_that_learned_something_passes(self):
        """Mean near the base rate is fine when the fixed-threshold accuracy
        beats it -- that is a calibrated detector rather than a constant."""
        self.assertTrue(checks.collapsed_to_prior(
            mean_probability=0.94, base_rate=0.94,
            accuracy_at_half=0.99)["ok"])

    def test_a_distribution_centred_elsewhere_passes(self):
        """The temperature arm: mean moved to 0.497 and accuracy stayed at
        0.116, which is uninformative but not a collapse onto the prior --
        and the two failures want different fixes."""
        self.assertTrue(checks.collapsed_to_prior(
            mean_probability=0.4974, base_rate=0.94,
            accuracy_at_half=0.116)["ok"])

    def test_a_balanced_population_is_handled(self):
        """At a 0.5 base rate, a constant predictor is still a collapse."""
        self.assertFalse(checks.collapsed_to_prior(
            mean_probability=0.5, base_rate=0.5, accuracy_at_half=0.5)["ok"])


class TestFixtureIndependence(unittest.TestCase):
    """`infer_relations` matched on one of four combinations — the one whose
    every half was hand-written."""

    @staticmethod
    def contains(target, predicate):
        t = target.replace("-", " ")
        p = predicate.replace("-", " ")
        return t in p or p in t

    def test_the_real_matcher_fault_is_caught(self):
        out = checks.fixture_independence(
            self.contains,
            measured={"target": "axle-set figure", "predicate": "tyre pressure"},
            fixture={"target": "axle-set",
                     "predicate": "tyre pressure for the axle set"})
        self.assertFalse(out["ok"])
        self.assertIn("fixture encodes the answer", out["note"])
        self.assertEqual(
            out["combinations"]["predicate=fixture, target=fixture"], True)
        self.assertEqual(
            out["combinations"]["predicate=measured, target=measured"], False)

    def test_a_matcher_that_also_works_on_measured_input_passes(self):
        out = checks.fixture_independence(
            self.contains,
            measured={"target": "tyre pressure", "predicate": "tyre pressure"},
            fixture={"target": "axle-set",
                     "predicate": "tyre pressure for the axle set"})
        self.assertTrue(out["ok"])

    def test_every_combination_is_enumerated(self):
        out = checks.fixture_independence(
            self.contains,
            measured={"target": "a", "predicate": "b"},
            fixture={"target": "c", "predicate": "d"})
        self.assertEqual(len(out["combinations"]), 4)


class TestVerify(unittest.TestCase):
    def test_a_failing_check_does_not_raise_by_default(self):
        """A harness that refuses to record a run because a check failed
        destroys the evidence of the failure, and three runs were already lost
        this session to dying before the write."""
        block = checks.verify(ceiling={"ok": False, "note": "arm above"})
        self.assertFalse(block["ok"])
        self.assertEqual(block["failed"], ["ceiling"])

    def test_raise_on_fail_names_the_reason(self):
        with self.assertRaises(AssertionError) as caught:
            checks.verify(raise_on_fail=True,
                          ceiling={"ok": False, "note": "arm above ceiling"})
        self.assertIn("arm above ceiling", str(caught.exception))

    def test_all_passing_is_ok(self):
        block = checks.verify(a={"ok": True}, b={"ok": True})
        self.assertTrue(block["ok"])
        self.assertEqual(block["failed"], [])

    def test_the_checks_are_carried_in_the_block(self):
        """The block goes into the result, so every run carries its own audit
        rather than relying on someone having looked."""
        block = checks.verify(ceiling={"ok": True, "ceiling": 1.0})
        self.assertEqual(block["ceiling"]["ceiling"], 1.0)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
