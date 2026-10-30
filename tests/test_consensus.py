"""Support counted by independent source: repetition is not consensus."""

from __future__ import annotations

import unittest

from memory_fabric import MemoryFabric
from memory_fabric.consensus import support

CLAIM = "Compressor K-31: the relief pressure is 14 bar."


class Consensus(unittest.TestCase):
    def setUp(self) -> None:
        self.f = MemoryFabric(auto_activate=True, hold_suspicious=False)
        self.addCleanup(self.f.close)

    def test_five_agents_repeating_one_source_are_one_source(self) -> None:
        origin = self.f.remember("ag_0", "Compressor K-31: the relief pressure is 22 bar.")
        for i in range(1, 5):
            self.f.derive(f"ag_{i}", "Compressor K-31: the relief pressure is 22 bar (as reported).",
                          [origin])
        honest_a = self.f.remember("ag_field_a", "Compressor K-31 relief pressure measured at 14 bar Monday.")
        honest_b = self.f.remember("ag_field_b", "Field check: compressor K-31 relief setpoint reads 14 bar.")
        s = support(self.f, CLAIM)
        loud = next(v for v in s.values if v.value == "22")
        quiet = next(v for v in s.values if v.value == "14")
        self.assertEqual(len(loud.agents), 5)
        self.assertEqual(loud.independent_sources, 1)
        self.assertTrue(loud.artificial)
        self.assertEqual(quiet.independent_sources, 2)
        self.assertEqual(s.leading, "14", "independent sources lead, not agent count")
        self.assertTrue(honest_a and honest_b)

    def test_independent_reports_are_counted(self) -> None:
        for i, text in enumerate(("Compressor K-31 relief pressure measured at 14 bar Monday.",
                                  "Field check: compressor K-31 relief setpoint reads 14 bar.",
                                  "Night shift saw compressor K-31 relief valve lift near 14 bar.")):
            self.f.remember(f"ag_obs_{i}", text)
        s = support(self.f, CLAIM)
        self.assertEqual(s.values[0].independent_sources, 3)
        self.assertFalse(s.values[0].artificial)

    def test_a_tie_is_contested(self) -> None:
        self.f.remember("ag_a", CLAIM)
        self.f.remember("ag_b", "Compressor K-31: the relief pressure is 19 bar.")
        s = support(self.f, CLAIM)
        self.assertTrue(s.contested)
        self.assertIsNone(s.leading)

    def test_withdrawn_support_does_not_count(self) -> None:
        a = self.f.remember("ag_a", "Compressor K-31 relief pressure measured at 14 bar Monday.")
        self.f.remember("ag_b", "Field check: compressor K-31 relief setpoint reads 14 bar.")
        self.f.quarantine(a, reason="wrong unit", basis="contradicted")
        counted = {m for v in support(self.f, CLAIM).values for m in v.memories}
        self.assertNotIn(a, counted)

    def test_identical_wording_counts_once(self) -> None:
        """Copy recognition: the same sentence from two agents is one source (the cautious side)."""
        self.f.remember("ag_a", CLAIM)
        self.f.remember("ag_b", CLAIM)
        self.assertEqual(support(self.f, CLAIM).values[0].independent_sources, 1)

    def test_other_units_and_parameters_are_not_the_same_claim(self) -> None:
        self.f.remember("ag_a", "Compressor K-13: the relief pressure is 14 bar.")
        self.f.remember("ag_b", "Compressor K-31: the torque setting is 14 Nm.")
        self.assertEqual(support(self.f, CLAIM).values, ())


if __name__ == "__main__":
    unittest.main()
