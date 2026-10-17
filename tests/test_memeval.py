"""memeval: known-answer tests built from this repository's own published errors.

Each case reconstructs, in miniature, a result Memory Fabric reported and
later had to correct, and asserts the contract refuses it. If one of these
starts passing as SUPPORTED, the harness has lost the property it exists for.
"""

from __future__ import annotations

import ast
import math
from pathlib import Path

import unittest

import memeval
from memeval import Outcome, Registration, checks, power, stats

PACKAGE = Path(memeval.__file__).resolve().parent


def approx(actual: float, expected: float, abs: float = 1e-6) -> bool:
    """`pytest.approx`, without pytest: CI runs `unittest` with nothing installed."""
    return math.isclose(actual, expected, rel_tol=1e-6, abs_tol=abs)


def reg(**overrides) -> Registration:
    fields = dict(hypothesis="h", metric="success", mechanism="mine",
                  baselines=["vector"], ceiling="oracle")
    fields.update(overrides)
    return Registration(**fields)


# --- independence ----------------------------------------------------------


class TestMemeval(unittest.TestCase):
    """One case per historical failure, plus the closed forms."""

    def test_memeval_imports_nothing_outside_the_standard_library(self) -> None:
        allowed = {"__future__", "dataclasses", "enum", "typing", "math",
                   "random", "collections", "itertools"}
        for path in PACKAGE.glob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    names = [a.name.split(".")[0] for a in node.names]
                elif isinstance(node, ast.ImportFrom):
                    if node.level:          # relative: inside memeval
                        continue
                    names = [(node.module or "").split(".")[0]]
                else:
                    continue
                for name in names:
                    assert name in allowed, f"{path.name} imports {name}"


    def test_the_licence_copy_matches_the_root(self) -> None:
        root = PACKAGE.parent / "LICENSE"
        assert (PACKAGE / "LICENSE").read_bytes() == root.read_bytes()


    def test_experiments_checks_is_the_same_module(self) -> None:
        from experiments import checks as legacy
        assert legacy.baseline_max is checks.baseline_max
        assert legacy.ceiling is checks.ceiling


    # --- the historical failures -----------------------------------------------


    def test_x1_a_quoted_baseline_is_invalid(self) -> None:
        # X1 registered sufficiency@5 and took B=0.000 from a table of nDCG@3.
        # The run never measured the baseline, so the contract refuses.
        arms = {"mine": {"success": 0.40}, "oracle": {"success": 1.00}}
        v = reg().evaluate(arms, seeds=5)
        assert v.outcome is Outcome.INVALID
        assert "not measured in this run" in v.reasons[0]


    def test_x1_measured_properly_is_abandoned(self) -> None:
        # Measured on the registered metric, the lexical baseline reached 1.000.
        arms = {"vector": {"success": 1.0}, "mine": {"success": 1.0},
                "oracle": {"success": 1.0}}
        v = reg().evaluate(arms, seeds=5)
        assert v.outcome is Outcome.ABANDONED
        assert v.headroom == 0.0


    def test_p2_a_baseline_that_maxes_the_metric_abandons(self) -> None:
        # full_context reached the oracle's 0.800: sufficiency bought with context.
        arms = {"full_context": {"success": 0.80}, "vector": {"success": 0.35},
                "mine": {"success": 0.70}, "oracle": {"success": 0.80}}
        v = reg(baselines=["vector", "full_context"]).evaluate(arms, seeds=5)
        assert v.outcome is Outcome.ABANDONED
        # Without full_context the same run would look like a clear pass --
        # which is why every registered baseline has to be in the comparison.
        alone = reg().evaluate(arms, seeds=5)
        assert alone.outcome is Outcome.SUPPORTED


    def test_h3_headroom_below_any_useful_margin_abandons(self) -> None:
        # H3's total available gain was at most +0.027.
        arms = {"vector": {"success": 0.600}, "mine": {"success": 0.620},
                "oracle": {"success": 0.627}}
        assert reg().evaluate(arms, seeds=5).outcome is Outcome.ABANDONED
        problems = reg().check_before_run(n_pairs=2000, expected_discordance=0.1,
                                          expected_headroom=0.027)
        assert any("abandonment threshold" in p for p in problems)


    def test_phase_a_an_arm_above_the_ceiling_is_invalid(self) -> None:
        # Phase A's oracle was capped by its retrieval budget; an arm beat it.
        arms = {"vector": {"success": 0.50}, "mine": {"success": 0.90},
                "oracle": {"success": 0.85}}
        v = reg().evaluate(arms, seeds=5)
        assert v.outcome is Outcome.INVALID
        assert "above the ceiling" in v.reasons[0]


    def test_an_unregistered_arm_above_the_ceiling_still_invalidates(self) -> None:
        # The check is over every arm in the run, not only the registered ones.
        arms = {"vector": {"success": 0.50}, "mine": {"success": 0.70},
                "exploratory": {"success": 0.95}, "oracle": {"success": 0.90}}
        assert reg().evaluate(arms, seeds=5).outcome is Outcome.INVALID


    def test_x4_an_underpowered_run_is_not_a_result(self) -> None:
        # X4-shaped: an MDE of ~0.14 against a pass margin of 0.08.
        arms = {"vector": {"success": 0.60}, "mine": {"success": 0.70},
                "oracle": {"success": 0.80}}
        v = reg().evaluate(arms, seeds=5, n_pairs=80, discordance=0.20)
        assert v.outcome is Outcome.UNDERPOWERED
        assert approx(v.realised_mde, 0.14, abs=0.001)
        # The same arms with enough pairs give a verdict.
        v = reg().evaluate(arms, seeds=5, n_pairs=1000, discordance=0.20)
        assert v.outcome is Outcome.SUPPORTED


    def test_x4_underpowering_is_visible_before_the_run(self) -> None:
        problems = reg(min_effect=0.04).check_before_run(
            n_pairs=80, expected_discordance=0.20, expected_headroom=0.20)
        assert any("cannot resolve" in p for p in problems)
        assert any("could not be told from noise" in p for p in problems)
        assert reg(min_effect=0.04).check_before_run(
            n_pairs=1000, expected_discordance=0.20, expected_headroom=0.20) == []


    def test_too_few_seeds_is_invalid(self) -> None:
        arms = {"vector": {"success": 0.2}, "mine": {"success": 0.9},
                "oracle": {"success": 1.0}}
        v = reg().evaluate(arms, seeds=1)
        assert v.outcome is Outcome.INVALID
        assert "seed" in v.reasons[0]


    def test_abstention_complement_is_flagged(self) -> None:
        # abstention-signals.md published 0.319, the complement of 0.682.
        positive = [0.1, 0.2, 0.3, 0.6]
        negative = [0.5, 0.7, 0.8, 0.4]
        # The check cannot know which orientation is right; it makes the wrong one
        # visible by printing both and saying which side of chance the claim is.
        row = checks.direction(positive, negative, expect="negative_scores_higher")
        flipped = checks.direction(negative, positive,
                                   expect="negative_scores_higher")
        assert row["auc"] == flipped["auc_if_reversed"]
        assert row["above_chance"] and not flipped["above_chance"]


    # --- the verdicts it should give --------------------------------------------


    def test_bar_is_a_share_of_headroom(self) -> None:
        arms = {"vector": {"success": 0.50}, "mine": {"success": 0.62},
                "oracle": {"success": 0.80}}
        v = reg().evaluate(arms, seeds=5)
        assert approx(v.bar, 0.62)
        assert v.outcome is Outcome.SUPPORTED
        arms["mine"]["success"] = 0.61
        assert reg().evaluate(arms, seeds=5).outcome is Outcome.NOT_SUPPORTED


    def test_headroom_on_the_float_boundary_abandons(self) -> None:
        arms = {"vector": {"success": 0.95}, "mine": {"success": 1.0},
                "oracle": {"success": 1.0}}
        assert reg().evaluate(arms, seeds=5).outcome is Outcome.ABANDONED


    def test_registration_rejects_a_mechanism_that_is_its_own_baseline(self) -> None:
        with self.assertRaises(ValueError):
            reg(baselines=["mine"])
        with self.assertRaises(ValueError):
            reg(baselines=[])


    def test_verdict_serialises(self) -> None:
        arms = {"vector": {"success": 0.5}, "mine": {"success": 0.7},
                "oracle": {"success": 0.8}}
        out = reg().evaluate(arms, seeds=5).to_json()
        assert out["outcome"] == "SUPPORTED"


    # --- power and statistics ------------------------------------------------------


    def test_power_closed_forms(self) -> None:
        assert approx(power.mde_paired(100, 0.25), 2.80 * 0.05)
        n = power.pairs_needed(0.04, 0.2)
        assert power.mde_paired(n, 0.2) <= 0.04 < power.mde_paired(n - 1, 0.2)
        # A zero at n=30 is consistent with a 9.5% rate.
        assert approx(power.absence_bound(30), 0.0950, abs=1e-3)
        assert approx(power.mde_independent(100, 0.5), 2.80 * math.sqrt(0.5 / 100))


    def test_paired_bootstrap_preserves_pairing(self) -> None:
        left = [1, 1, 0, 1, 1, 0, 1, 1, 1, 1] * 10
        right = [1, 0, 0, 1, 0, 0, 1, 1, 1, 0] * 10
        interval, discordance = stats.paired_difference(left, right)
        assert approx(interval.point, 0.3)
        assert approx(discordance, 0.3)
        assert interval.excludes_zero
        # Deterministic for a given seed.
        again, _ = stats.paired_difference(left, right)
        assert again == interval


    def test_equivalence_is_not_failure_to_exclude_zero(self) -> None:
        wide = stats.Interval(point=0.0, low=-0.3, high=0.3, n=10)
        assert not wide.excludes_zero and not wide.within(0.05)
        tight = stats.Interval(point=0.0, low=-0.02, high=0.03, n=1000)
        assert tight.within(0.05)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
