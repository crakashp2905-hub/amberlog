"""Exposure policies, and the correctness of the propensities they report.

A logged propensity that does not match the policy's actual behaviour is worse
than no propensity at all: it silently biases every estimate built on it, and
nothing downstream can detect the error. So these tests check the reported
numbers against observed frequencies rather than against the formula that
produced them.
"""

from __future__ import annotations

import random
import unittest
from collections import Counter

from memory_fabric.exposure import (
    AlwaysExposePolicy,
    Candidate,
    EpsilonGreedyPolicy,
    ExposureDecision,
    TopKPolicy,
    build_policy,
)
from memory_fabric.model import ValueEstimate


def candidate(name: str, relevance: float, value: float = 0.0) -> Candidate:
    return Candidate(
        memory_id=name,
        version=1,
        relevance=relevance,
        value=ValueEstimate(
            mean=value, ci_low=value, ci_high=value, n_eff=10.0, estimator="t", contrastive=True
        ),
    )


class TestDecisionContract(unittest.TestCase):
    def test_propensity_must_be_a_probability(self) -> None:
        for bad in (0.0, -0.1, 1.5):
            with self.assertRaises(ValueError):
                ExposureDecision(candidate=candidate("a", 1.0), exposed=True, propensity=bad)

    def test_valid_propensity_is_accepted(self) -> None:
        decision = ExposureDecision(candidate=candidate("a", 1.0), exposed=True, propensity=1.0)
        self.assertEqual(decision.propensity, 1.0)


class TestTopK(unittest.TestCase):
    def setUp(self) -> None:
        self.rng = random.Random(0)
        self.candidates = [
            candidate("low", 0.1, value=0.9),
            candidate("high", 0.9, value=0.1),
            candidate("mid", 0.5, value=0.5),
        ]

    def test_exposes_the_k_most_relevant(self) -> None:
        decisions = TopKPolicy("relevance").decide(self.candidates, k=2, rng=self.rng)
        exposed = {d.candidate.memory_id for d in decisions if d.exposed}
        self.assertEqual(exposed, {"high", "mid"})

    def test_can_rank_by_value_instead(self) -> None:
        decisions = TopKPolicy("value").decide(self.candidates, k=2, rng=self.rng)
        exposed = {d.candidate.memory_id for d in decisions if d.exposed}
        self.assertEqual(exposed, {"low", "mid"})

    def test_reports_no_overlap(self) -> None:
        """A deterministic policy must declare that its data cannot support
        causal estimation, rather than leaving estimators to assume it can."""
        self.assertFalse(TopKPolicy().declares_overlap)

    def test_decides_every_candidate(self) -> None:
        """The exposure invariant: a withheld candidate is logged too, or the
        withheld arm silently disappears from the data (SPEC.md section 4)."""
        decisions = TopKPolicy().decide(self.candidates, k=1, rng=self.rng)
        self.assertEqual(len(decisions), len(self.candidates))
        self.assertEqual(sum(1 for d in decisions if d.exposed), 1)

    def test_ties_break_deterministically(self) -> None:
        tied = [candidate("b", 0.5), candidate("a", 0.5), candidate("c", 0.5)]
        first = TopKPolicy().decide(tied, k=2, rng=random.Random(1))
        second = TopKPolicy().decide(tied, k=2, rng=random.Random(2))
        self.assertEqual(
            [d.candidate.memory_id for d in first if d.exposed],
            [d.candidate.memory_id for d in second if d.exposed],
        )

    def test_rejects_an_unknown_ranking_key(self) -> None:
        with self.assertRaises(ValueError):
            TopKPolicy("popularity")


class TestEpsilonGreedy(unittest.TestCase):
    def test_reported_propensities_match_observed_frequencies(self) -> None:
        """The central check: does the logged number describe what happened?

        Each candidate is decided many times; the share of trials in which it
        was exposed must match the propensity the policy reported for exposure.
        """
        epsilon = 0.3
        policy = EpsilonGreedyPolicy(epsilon=epsilon, rank_by="relevance")
        rng = random.Random(12345)
        candidates = [candidate("top", 0.9), candidate("bottom", 0.1)]

        trials = 20000
        exposed_counts: Counter[str] = Counter()
        reported: dict[str, float] = {}

        for _ in range(trials):
            for decision in policy.decide(candidates, k=1, rng=rng):
                name = decision.candidate.memory_id
                if decision.exposed:
                    exposed_counts[name] += 1
                    reported[name] = decision.propensity
                else:
                    # P(expose) is the complement of a withheld decision's own
                    # propensity, so both branches must agree on the same value.
                    reported.setdefault(name, 1.0 - decision.propensity)

        # Greedy pick: (1 - eps) * 1 + eps * 0.5
        expected_top = (1 - epsilon) + epsilon * 0.5
        # Non-pick: eps * 0.5
        expected_bottom = epsilon * 0.5

        self.assertAlmostEqual(exposed_counts["top"] / trials, expected_top, delta=0.02)
        self.assertAlmostEqual(exposed_counts["bottom"] / trials, expected_bottom, delta=0.02)
        self.assertAlmostEqual(reported["top"], expected_top, places=6)
        self.assertAlmostEqual(reported["bottom"], expected_bottom, places=6)

    def test_withheld_propensity_is_the_complement(self) -> None:
        policy = EpsilonGreedyPolicy(epsilon=0.2, rank_by="relevance")
        rng = random.Random(7)
        candidates = [candidate("top", 0.9), candidate("bottom", 0.1)]
        seen: dict[tuple[str, bool], float] = {}
        for _ in range(2000):
            for decision in policy.decide(candidates, k=1, rng=rng):
                seen[(decision.candidate.memory_id, decision.exposed)] = decision.propensity
        for name in ("top", "bottom"):
            self.assertAlmostEqual(seen[(name, True)] + seen[(name, False)], 1.0, places=9)

    def test_creates_overlap_in_both_directions(self) -> None:
        """Both arms must occur for every candidate, or there is nothing to
        compare and IPS will refuse to answer."""
        policy = EpsilonGreedyPolicy(epsilon=0.25, rank_by="relevance")
        rng = random.Random(3)
        candidates = [candidate("top", 0.9), candidate("bottom", 0.1)]
        outcomes: set[tuple[str, bool]] = set()
        for _ in range(500):
            for decision in policy.decide(candidates, k=1, rng=rng):
                outcomes.add((decision.candidate.memory_id, decision.exposed))
        self.assertEqual(len(outcomes), 4)

    def test_declares_overlap(self) -> None:
        self.assertTrue(EpsilonGreedyPolicy().declares_overlap)

    def test_rejects_a_degenerate_epsilon(self) -> None:
        """eps of 0 or 1 destroys overlap, so the policy refuses to be built
        that way rather than silently producing unusable data."""
        for bad in (0.0, 1.0, -0.1, 1.2):
            with self.assertRaises(ValueError):
                EpsilonGreedyPolicy(epsilon=bad)

    def test_is_reproducible_for_a_fixed_seed(self) -> None:
        policy = EpsilonGreedyPolicy(epsilon=0.3)
        candidates = [candidate("a", 0.9), candidate("b", 0.5), candidate("c", 0.1)]
        first = [d.exposed for d in policy.decide(candidates, 2, random.Random(99))]
        second = [d.exposed for d in policy.decide(candidates, 2, random.Random(99))]
        self.assertEqual(first, second)


class TestPolicyRegistry(unittest.TestCase):
    def test_builds_known_policies(self) -> None:
        self.assertIsInstance(build_policy("top_k"), TopKPolicy)
        self.assertIsInstance(build_policy("epsilon_greedy"), EpsilonGreedyPolicy)
        self.assertIsInstance(build_policy("always"), AlwaysExposePolicy)

    def test_passes_through_an_instance(self) -> None:
        policy = TopKPolicy("value")
        self.assertIs(build_policy(policy), policy)

    def test_rejects_an_unknown_name(self) -> None:
        with self.assertRaises(KeyError):
            build_policy("magic")


if __name__ == "__main__":
    unittest.main()


class TestValueRankingFallsBackToRelevance(unittest.TestCase):
    """Ranking by value must not become ranking by creation time.

    Found while building Phase B. `value_mean` is 0.0 for a memory nothing is
    known about, so in a store with no value evidence every candidate tied at
    zero and the sort fell through to the memory id. Ids are ULIDs, which are
    time-ordered, so the oldest memories were exposed every time and relevance
    was discarded. A newly written or imported memory could never be exposed,
    and value evidence can only be earned by exposure — a deadlock that only
    epsilon exploration broke, weakly. In a four-agent federation with 36
    imports competing for three slots, not one import was retrieved across
    eight consecutive episodes.
    """

    def _candidates(self):
        # Ids ascending, so a tie-break on id picks `old` first; relevance says
        # the opposite, and relevance is the only signal that exists here.
        return [
            Candidate(memory_id="01AAA", version=1, relevance=0.10, value=None),
            Candidate(memory_id="01BBB", version=1, relevance=0.90, value=None),
        ]

    def test_top_k_on_value_prefers_the_relevant_one_when_nothing_is_known(self) -> None:
        policy = TopKPolicy(rank_by="value")
        decisions = policy.decide(self._candidates(), 1, random.Random(0))
        exposed = [d.candidate.memory_id for d in decisions if d.exposed]
        self.assertEqual(exposed, ["01BBB"])

    def test_epsilon_greedy_on_value_ranks_the_same_way(self) -> None:
        """Epsilon must be in (0, 1) for the policy to have overlap at all, so
        the greedy choice is checked through the propensities: the relevant
        candidate is the one the ranking favours, and its reported P(expose) is
        the high one."""
        policy = EpsilonGreedyPolicy(epsilon=0.2, rank_by="value")
        decisions = policy.decide(self._candidates(), 1, random.Random(0))
        chance = {
            d.candidate.memory_id: (
                d.propensity if d.exposed else 1.0 - d.propensity
            )
            for d in decisions
        }
        self.assertGreater(chance["01BBB"], chance["01AAA"])

    def test_measured_value_still_wins_over_relevance(self) -> None:
        """The fallback must not override evidence: a memory measured to help
        beats a more similar memory nothing is known about."""
        candidates = [
            Candidate(
                memory_id="01AAA", version=1, relevance=0.10,
                value=ValueEstimate(
                    mean=0.8, ci_low=0.5, ci_high=1.0,
                    n_eff=12.0, estimator="test", contrastive=True,
                ),
            ),
            Candidate(memory_id="01BBB", version=1, relevance=0.90, value=None),
        ]
        policy = TopKPolicy(rank_by="value")
        decisions = policy.decide(candidates, 1, random.Random(0))
        exposed = [d.candidate.memory_id for d in decisions if d.exposed]
        self.assertEqual(exposed, ["01AAA"])

    def test_evidence_means_the_estimate_would_survive_being_acted_on(self) -> None:
        """`has_value_evidence` asks whether the number is worth acting on, not
        merely whether a number exists.

        It originally asked only `n_eff > 0`, which let a single observation
        with an interval spanning zero outrank an unevaluated memory nineteen
        times more relevant. It now applies the rule the firewall already uses
        for scope promotion: contrastive, and the interval clear of zero.
        """
        unknown = Candidate(memory_id="01AAA", version=1, relevance=0.5, value=None)

        def estimate(mean, low, high, n, contrastive=True):
            return ValueEstimate(
                mean=mean, ci_low=low, ci_high=high, n_eff=n,
                estimator="test", contrastive=contrastive,
            )

        # A measured zero: plenty of evidence, and it says the memory does
        # nothing. Not grounds to rank it on, because the interval spans zero.
        measured_zero = Candidate("01BBB", 1, 0.5, estimate(0.0, -0.1, 0.1, 20.0))
        # Thin and inconclusive.
        thin = Candidate("01CCC", 1, 0.5, estimate(0.10, -0.40, 0.60, 1.0))
        # Non-contrastive: an absolute rate cannot show the memory helped.
        absolute = Candidate(
            "01DDD", 1, 0.5, estimate(0.8, 0.6, 0.9, 30.0, contrastive=False)
        )
        # Real evidence, in both directions.
        helps = Candidate("01EEE", 1, 0.5, estimate(0.8, 0.5, 1.0, 12.0))
        harms = Candidate("01FFF", 1, 0.5, estimate(-0.6, -0.9, -0.3, 11.0))

        self.assertEqual(unknown.value_mean, measured_zero.value_mean)
        for candidate in (unknown, measured_zero, thin, absolute):
            self.assertFalse(candidate.has_value_evidence, candidate.memory_id)
        for candidate in (helps, harms):
            self.assertTrue(candidate.has_value_evidence, candidate.memory_id)

    def test_thin_evidence_does_not_outrank_strong_relevance(self) -> None:
        """The defect this fix exists for, as a test."""
        thin = Candidate(
            "01AAA", 1, 0.05,
            ValueEstimate(mean=0.10, ci_low=-0.40, ci_high=0.60, n_eff=1.0,
                          estimator="test", contrastive=True),
        )
        relevant = Candidate("01BBB", 1, 0.95, None)
        decisions = TopKPolicy(rank_by="value").decide(
            [thin, relevant], 1, random.Random(0)
        )
        self.assertEqual(
            [d.candidate.memory_id for d in decisions if d.exposed], ["01BBB"]
        )

    def test_a_memory_measured_to_harm_ranks_below_an_unevaluated_one(self) -> None:
        harms = Candidate(
            "01AAA", 1, 0.95,
            ValueEstimate(mean=-0.6, ci_low=-0.9, ci_high=-0.3, n_eff=11.0,
                          estimator="test", contrastive=True),
        )
        unknown = Candidate("01BBB", 1, 0.50, None)
        decisions = TopKPolicy(rank_by="value").decide(
            [harms, unknown], 1, random.Random(0)
        )
        self.assertEqual(
            [d.candidate.memory_id for d in decisions if d.exposed], ["01BBB"]
        )
