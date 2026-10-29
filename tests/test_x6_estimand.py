"""Known-answer tests for X6's estimand: the diagonal interaction.

AGENTS.md requires estimators to carry known-answer tests. This one matters
more than most, because the naive measure of portability -- how well does B do
with A's memories? -- is confounded with how well A writes, and the whole
design rests on the decomposition separating the two.

The tests construct matrices whose answer is arithmetic, and pin both the
property the design needs (writer quality gives D = 0) and the scaling found
before the run (D is (n-1)/n of the true own-memory bonus).
"""

from __future__ import annotations

import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from experiments.x6_cross_model import (  # noqa: E402
    diagonal_interaction, own_memory_bonus,
)

M = ["a", "b", "c"]


def additive(reader, writer, mu=0.5):
    return {(r, w): mu + reader[r] + writer[w] for r in M for w in M}


class TestWriterQualityIsNotPortability(unittest.TestCase):
    """The confound the design exists to remove."""

    def test_pure_main_effects_give_zero(self):
        m = additive({"a": 0.1, "b": 0.0, "c": -0.1},
                     {"a": 0.2, "b": 0.0, "c": -0.2})
        self.assertAlmostEqual(diagonal_interaction(m, M), 0.0, places=12)

    def test_one_great_writer_gives_zero(self):
        """A writer whose lessons help every reader. The naive measure reports
        this as a portability effect; the decomposition must not."""
        m = {(r, w): 0.5 + (0.3 if w == "a" else 0.0) for r in M for w in M}
        self.assertAlmostEqual(diagonal_interaction(m, M), 0.0, places=12)

    def test_one_great_reader_gives_zero(self):
        m = {(r, w): 0.5 + (0.3 if r == "a" else 0.0) for r in M for w in M}
        self.assertAlmostEqual(diagonal_interaction(m, M), 0.0, places=12)

    def test_a_constant_matrix_gives_zero(self):
        m = {(r, w): 0.42 for r in M for w in M}
        self.assertAlmostEqual(diagonal_interaction(m, M), 0.0, places=12)


class TestAnOwnMemoryBonusIsDetected(unittest.TestCase):
    def test_a_diagonal_bonus_gives_two_thirds_of_it(self):
        """D = b(n-1)/n. A bonus of 0.1 on three models is D = 0.0667 -- the
        scaling found before the run and recorded in the registration."""
        base = additive({"a": 0.1, "b": 0.0, "c": -0.1},
                        {"a": 0.0, "b": 0.05, "c": -0.05})
        m = {k: v + (0.1 if k[0] == k[1] else 0.0) for k, v in base.items()}
        self.assertAlmostEqual(diagonal_interaction(m, M), 0.1 * 2 / 3,
                               places=12)

    def test_the_bonus_is_recovered(self):
        base = additive({"a": 0.0, "b": 0.0, "c": 0.0},
                        {"a": 0.0, "b": 0.0, "c": 0.0})
        m = {k: v + (0.12 if k[0] == k[1] else 0.0) for k, v in base.items()}
        d = diagonal_interaction(m, M)
        self.assertAlmostEqual(own_memory_bonus(d, 3), 0.12, places=12)

    def test_a_penalty_reads_as_negative(self):
        """A model that reads its own memories WORSE -- e.g. it over-trusts its
        own phrasing -- must not be folded into zero."""
        m = {(r, w): 0.5 - (0.09 if r == w else 0.0) for r in M for w in M}
        self.assertLess(diagonal_interaction(m, M), 0.0)
        self.assertAlmostEqual(own_memory_bonus(diagonal_interaction(m, M), 3),
                               -0.09, places=12)


class TestScaling(unittest.TestCase):
    def test_the_scaling_holds_for_other_sizes(self):
        for n in (2, 3, 4, 6):
            names = [f"m{i}" for i in range(n)]
            m = {(r, w): 0.3 + (0.2 if r == w else 0.0)
                 for r in names for w in names}
            d = diagonal_interaction(m, names)
            self.assertAlmostEqual(d, 0.2 * (n - 1) / n, places=12, msg=n)
            self.assertAlmostEqual(own_memory_bonus(d, n), 0.2, places=12)

    def test_one_model_is_its_own_bonus(self):
        """No off-diagonal to compare against; the conversion is the identity
        rather than a division by zero."""
        self.assertEqual(own_memory_bonus(0.3, 1), 0.3)

    def test_the_oracle_column_is_excluded(self):
        """The oracle is a bound, not a writer. A reader's skill with perfect
        lessons must not leak into how it reads another model's."""
        m = {(r, w): 0.5 for r in M for w in M}
        m.update({(r, "oracle"): 0.99 for r in M})
        self.assertAlmostEqual(diagonal_interaction(m, M), 0.0, places=12)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
