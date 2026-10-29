"""Known-answer controls for the scripted action study."""
import unittest

from benchmarks.three_agent import run


class ThreeAgent(unittest.TestCase):
    def test_cached_baseline_exposes_the_failure_and_recheck_matches_oracle(self):
        cached = run(601, "shared_cached")["counts"]
        self.assertEqual(cached["attempted"], 36)
        self.assertEqual(cached["stale_actions"], 18)
        oracle = run(601, "oracle")["counts"]
        for arm in ("shared_recheck", "governed"):
            self.assertEqual(run(601, arm)["counts"], oracle)
        self.assertEqual(oracle["correct_abstention"], 18)
        self.assertEqual(oracle["task_success"], 18)

    def test_unknown_arm_is_not_silently_scored_as_oracle(self):
        with self.assertRaises(ValueError):
            run(601, "typo")
