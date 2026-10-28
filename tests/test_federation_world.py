import unittest

from benchmarks.federation_world import run_seed


class WorldTests(unittest.TestCase):
    def test_partition_is_visible_and_rejoin_invalidates_dependent_actions(self):
        for topology in ("chain", "star"):
            with self.subTest(topology=topology):
                row = run_seed(3, topology)
                self.assertEqual(row["allowed_before"], 5)
                self.assertEqual(row["stale_during_partition"], 4)
                self.assertEqual(row["withdrawn_after_rejoin"], 5)
                self.assertEqual(row["contested_derivatives"], 5)
                self.assertEqual(row["independent_survivors"], 5)
                self.assertEqual(row["stale_actions_after_rejoin"], 0)

    def test_scheduler_reproducibility(self):
        self.assertEqual(run_seed(7), run_seed(7))
