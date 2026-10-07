"""Known-answer tests for the bandit world and its topologies.

Everything H4 concludes rests on the belief update and the network structure
being right. Both fail silently if wrong — the simulation still produces
plausible-looking probabilities.
"""

from __future__ import annotations

import random
import unittest

from experiments.banditworld import (
    BAD,
    GOOD,
    TOPOLOGIES,
    BanditConfig,
    Beliefs,
    complete,
    cycle_sparse,
    isolated,
    ring,
    simulate,
    small_world,
)


class TestBeliefs(unittest.TestCase):
    def test_uniform_prior_starts_at_one_half(self) -> None:
        self.assertAlmostEqual(Beliefs().mean(GOOD), 0.5)

    def test_posterior_converges_on_the_observed_rate(self) -> None:
        belief = Beliefs()
        belief.observe(GOOD, 700, 1000)
        self.assertAlmostEqual(belief.mean(GOOD), 0.7, delta=0.01)

    def test_believes_the_higher_mean(self) -> None:
        belief = Beliefs()
        belief.observe(GOOD, 60, 100)
        belief.observe(BAD, 40, 100)
        self.assertEqual(belief.believes(), GOOD)

    def test_ties_break_toward_the_wrong_action(self) -> None:
        """A population that knows nothing must count as wrong, not be
        flattered by agents that happen to tie."""
        self.assertEqual(Beliefs().believes(), BAD)

    def test_intervals_narrow_with_evidence(self) -> None:
        few, many = Beliefs(), Beliefs()
        few.observe(GOOD, 3, 5)
        many.observe(GOOD, 600, 1000)
        width = lambda b: b.interval(GOOD)[1] - b.interval(GOOD)[0]  # noqa: E731
        self.assertGreater(width(few), width(many))

    def test_contested_resolves_once_evidence_separates_the_actions(self) -> None:
        belief = Beliefs()
        belief.observe(GOOD, 3, 5)
        belief.observe(BAD, 2, 5)
        self.assertTrue(belief.contested())

        belief.observe(GOOD, 900, 1000)
        belief.observe(BAD, 100, 1000)
        self.assertFalse(belief.contested())


class TestTopologies(unittest.TestCase):
    def setUp(self) -> None:
        self.rng = random.Random(0)
        self.n = 10

    def test_degrees_are_what_the_names_claim(self) -> None:
        expected = {
            "complete": 9,
            "small_world": 4,
            "ring": 2,
            "cycle_sparse": 1,
            "isolated": 0,
        }
        for name, degree in expected.items():
            with self.subTest(name=name):
                graph = TOPOLOGIES[name](self.n, random.Random(0))
                mean_degree = sum(len(g) for g in graph) / self.n
                self.assertAlmostEqual(mean_degree, degree, delta=0.5)

    def test_nobody_is_their_own_neighbour(self) -> None:
        for name, build in TOPOLOGIES.items():
            with self.subTest(name=name):
                for index, group in enumerate(build(self.n, random.Random(1))):
                    self.assertNotIn(index, group)

    def test_ring_and_complete_are_symmetric(self) -> None:
        for build in (complete, ring):
            graph = build(self.n, random.Random(0))
            for i, group in enumerate(graph):
                for j in group:
                    self.assertIn(i, graph[j])

    def test_cycle_sparse_connects_the_whole_population(self) -> None:
        """Degree 1 must still be connected, or it is not the sparse end of the
        axis — it is a second isolated condition."""
        graph = cycle_sparse(self.n, self.rng)
        seen, current = {0}, 0
        for _ in range(self.n):
            current = graph[current][0]
            seen.add(current)
        self.assertEqual(len(seen), self.n)

    def test_isolated_shares_nothing(self) -> None:
        self.assertTrue(all(not g for g in isolated(self.n, self.rng)))

    def test_small_world_rewiring_is_seeded(self) -> None:
        a = small_world(self.n, random.Random(3))
        b = small_world(self.n, random.Random(3))
        self.assertEqual(a, b)


class TestSimulation(unittest.TestCase):
    def test_runs_are_reproducible(self) -> None:
        config = BanditConfig(rounds=30)
        a = simulate(config, "ring", False, seed=5)
        b = simulate(config, "ring", False, seed=5)
        self.assertEqual(a.correct, b.correct)
        self.assertEqual(a.bad_pulls, b.bad_pulls)

    def test_an_obviously_better_action_is_found(self) -> None:
        """Sanity: with a wide payoff gap every topology should get it right."""
        config = BanditConfig(p_good=0.9, p_bad=0.1, rounds=60)
        for topology in ("complete", "ring", "cycle_sparse"):
            with self.subTest(topology=topology):
                correct = sum(
                    1 for seed in range(20)
                    if simulate(config, topology, False, seed).correct
                )
                self.assertGreaterEqual(correct, 18)

    def test_isolated_agents_without_preservation_get_stuck(self) -> None:
        """The absorbing trap: an agent that stops testing the better action
        never learns, and with no neighbours nothing rescues it."""
        config = BanditConfig(rounds=80)
        correct = sum(
            1 for seed in range(40)
            if simulate(config, "isolated", False, seed).correct
        )
        self.assertEqual(correct, 0)

    def test_preservation_rescues_isolated_agents(self) -> None:
        config = BanditConfig(rounds=80)
        correct = sum(
            1 for seed in range(40)
            if simulate(config, "isolated", True, seed).correct
        )
        self.assertGreater(correct, 0)

    def test_pull_accounting_adds_up(self) -> None:
        config = BanditConfig(rounds=25, n_agents=6, pulls_per_round=10)
        outcome = simulate(config, "ring", False, seed=1)
        self.assertEqual(
            outcome.total_pulls, config.rounds * config.n_agents * config.pulls_per_round
        )
        self.assertLessEqual(outcome.bad_pulls, outcome.total_pulls)

    def test_preservation_spends_pulls_on_the_minority(self) -> None:
        config = BanditConfig(rounds=25, n_agents=6)
        plain = simulate(config, "complete", False, seed=2)
        preserved = simulate(config, "complete", True, seed=2)
        self.assertEqual(plain.total_pulls, preserved.total_pulls)
        self.assertNotEqual(plain.bad_pulls, preserved.bad_pulls)

    def test_diverse_starting_beliefs(self) -> None:
        """Regression: identical planted failures made every agent start
        believing the same wrong thing, so nobody ever tested the better
        action and no topology could escape. P(correct) was 0.000 everywhere.
        """
        config = BanditConfig()
        rng = random.Random(0)
        starts = []
        for seed in range(30):
            outcome = simulate(config, "isolated", False, seed)
            starts.append(outcome.wrong_at_checkpoint)
        # Some populations start believing the right thing, some the wrong one.
        self.assertIn(True, starts)


if __name__ == "__main__":
    unittest.main()
