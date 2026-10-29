"""Known-answer tests for RuleWorld and its ground truth.

Everything H1 concludes rests on `ground_truth()` being right. If it drifts, the
experiment does not fail loudly — it reports a confident number about the wrong
quantity. So the values it produces are checked against the closed form derived
by hand from the agent's policy, and the designed confound is checked to be
actually present rather than assumed.
"""

from __future__ import annotations

import random
import unittest

from experiments.ruleworld import CLAIM, DISTRACTOR, RuleWorld, WorldConfig, query_for
from experiments.runner import RunConfig, ground_truth, estimable_memories, run
from amberlog.estimators import NaiveUsageEstimator


class TestWorldPolicy(unittest.TestCase):
    """`p_correct` is the closed form every treatment effect is derived from."""

    def setUp(self) -> None:
        self.world = RuleWorld(WorldConfig(compliance=0.8), random.Random(0))
        self.symptom = self.world.symptoms[0]
        self.rule = self.world.rules[self.symptom]

    def correct_claim(self) -> dict:
        return {"kind": CLAIM, "symptom": self.symptom, "action": self.rule.correct_action}

    def wrong_claim(self) -> dict:
        other = next(a for a in self.world.actions if a != self.rule.correct_action)
        return {"kind": CLAIM, "symptom": self.symptom, "action": other}

    def test_no_memory_means_guessing(self) -> None:
        self.assertAlmostEqual(
            self.world.p_correct(self.symptom, []), self.rule.guess_rate
        )

    def test_correct_claim_matches_the_closed_form(self) -> None:
        q = self.world.config.compliance
        expected = q * 1.0 + (1 - q) * self.rule.guess_rate
        self.assertAlmostEqual(
            self.world.p_correct(self.symptom, [self.correct_claim()]), expected
        )

    def test_wrong_claim_matches_the_closed_form(self) -> None:
        q = self.world.config.compliance
        expected = (1 - q) * self.rule.guess_rate
        self.assertAlmostEqual(
            self.world.p_correct(self.symptom, [self.wrong_claim()]), expected
        )

    def test_a_distractor_changes_nothing(self) -> None:
        """Its true value is exactly zero, which is what makes it the clean
        test of whether an estimator is fooled by the confound."""
        distractor = {"kind": DISTRACTOR, "symptom": self.symptom, "action": None}
        self.assertAlmostEqual(
            self.world.p_correct(self.symptom, [distractor]), self.rule.guess_rate
        )

    def test_a_claim_about_another_symptom_changes_nothing(self) -> None:
        other = self.world.symptoms[1]
        claim = {"kind": CLAIM, "symptom": other, "action": self.world.actions[0]}
        self.assertAlmostEqual(
            self.world.p_correct(self.symptom, [claim]), self.rule.guess_rate
        )

    def test_only_the_top_ranked_claim_counts(self) -> None:
        """The agent follows the first matching claim, so a correct claim below
        a wrong one does not rescue the answer."""
        ranked = [self.wrong_claim(), self.correct_claim()]
        q = self.world.config.compliance
        self.assertAlmostEqual(
            self.world.p_correct(self.symptom, ranked), (1 - q) * self.rule.guess_rate
        )

    def test_sampled_actions_agree_with_the_closed_form(self) -> None:
        """The simulation and the analytic model must not drift apart."""
        rng = random.Random(7)
        ranked = [self.correct_claim()]
        trials = 20000
        hits = sum(
            1
            for _ in range(trials)
            if self.world.act(self.symptom, ranked, rng) == self.rule.correct_action
        )
        self.assertAlmostEqual(
            hits / trials, self.world.p_correct(self.symptom, ranked), delta=0.02
        )

    def test_guessing_agrees_with_the_closed_form(self) -> None:
        rng = random.Random(9)
        trials = 20000
        hits = sum(
            1
            for _ in range(trials)
            if self.world.act(self.symptom, [], rng) == self.rule.correct_action
        )
        self.assertAlmostEqual(hits / trials, self.rule.guess_rate, delta=0.02)


class TestRetrieval(unittest.TestCase):
    def test_a_symptom_query_finds_memories_about_that_symptom(self) -> None:
        """If retrieval did not work, every memory would have true value zero
        and the experiment would measure nothing."""
        result = run(RunConfig(n_episodes=60, seed=0, epsilon=0.2))
        try:
            hits = result.fabric.index.search(query_for(result.world.symptoms[3]), k=5)
            self.assertTrue(hits)
            for memory_id, score in hits:
                self.assertGreater(score, 0.0)
                structured = result.fabric.get(memory_id).structured or {}
                self.assertEqual(structured.get("symptom"), result.world.symptoms[3])
        finally:
            result.close()


class TestGroundTruth(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.result = run(RunConfig(n_episodes=1500, seed=0, epsilon=0.2))
        cls.truth = ground_truth(cls.result)
        cls.by_kind: dict[str, list[float]] = {CLAIM: [], DISTRACTOR: []}
        cls.correct: list[float] = []
        cls.wrong: list[float] = []
        for seeded in cls.result.seeded:
            value = cls.truth.get(seeded.memory_id)
            if value is None:
                continue
            cls.by_kind[seeded.kind].append(value)
            if seeded.kind == CLAIM:
                rule = cls.result.world.rules[seeded.symptom]
                (cls.correct if seeded.action == rule.correct_action else cls.wrong).append(value)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.result.close()

    def test_distractors_have_exactly_zero_true_value(self) -> None:
        self.assertTrue(self.by_kind[DISTRACTOR])
        for value in self.by_kind[DISTRACTOR]:
            self.assertEqual(value, 0.0)

    def test_correct_claims_have_positive_true_value(self) -> None:
        self.assertTrue(self.correct)
        self.assertTrue(all(v > 0.0 for v in self.correct))

    def test_wrong_claims_never_have_positive_true_value(self) -> None:
        """A wrong claim can be inert rather than harmful: ranked below another
        matching claim it is never followed, so its effect is exactly zero. What
        it can never be is helpful."""
        self.assertTrue(self.wrong)
        self.assertTrue(all(v <= 0.0 for v in self.wrong))
        self.assertTrue(
            any(v < 0.0 for v in self.wrong),
            "no wrong claim was ever top-ranked, so harm is untested",
        )

    def test_true_value_never_exceeds_the_analytic_bound(self) -> None:
        """The largest possible swing is `q`.

        Not `q·(1 − guess_rate)`: that is the bound when the alternative is
        having no matching claim at all. The widest swing is a correct claim
        displacing a *wrong* one at the top of the ranking, which moves success
        from `(1−q)·guess_rate` to `q + (1−q)·guess_rate` — a difference of
        exactly `q`.
        """
        bound = self.result.world.config.compliance
        for seeded in self.result.seeded:
            value = self.truth.get(seeded.memory_id)
            if value is None:
                continue
            self.assertLessEqual(abs(value), bound + 1e-9)

    def test_ground_truth_covers_the_analysis_population(self) -> None:
        population = estimable_memories(self.result)
        missing = population - set(self.truth)
        self.assertEqual(missing, set())


class TestTheConfoundIsReal(unittest.TestCase):
    """The experiment must be able to fail.

    A distractor has true value zero. If the naive estimator nonetheless ranks
    distractors above genuinely harmful memories, the selection bias this whole
    milestone is about is present in the data — and if it were not, H1 would be
    a test of nothing.
    """

    def test_naive_credit_cannot_separate_worthless_from_valuable(self) -> None:
        """A distractor is worth exactly nothing and a correct claim is worth a
        lot, but both are retrieved on episodes that mostly succeed — so their
        observed success rates overlap. If they did not overlap, naive credit
        would already be sufficient and H1 would be testing nothing.
        """
        result = run(RunConfig(n_episodes=2000, seed=1, epsilon=0.2))
        try:
            truth = ground_truth(result)
            naive = NaiveUsageEstimator()
            naive.fit(result.fabric.state)

            distractors: list[float] = []
            correct: list[float] = []
            true_distractor: list[float] = []
            true_correct: list[float] = []
            for seeded in result.seeded:
                value = truth.get(seeded.memory_id)
                estimate = naive.estimate(seeded.memory_id)
                if value is None or estimate.n_eff <= 0.0:
                    continue
                rule = result.world.rules[seeded.symptom]
                if seeded.kind == DISTRACTOR:
                    distractors.append(estimate.mean)
                    true_distractor.append(value)
                elif seeded.action == rule.correct_action:
                    correct.append(estimate.mean)
                    true_correct.append(value)

            self.assertTrue(distractors and correct)

            # They really are very different memories.
            self.assertAlmostEqual(sum(true_distractor) / len(true_distractor), 0.0)
            self.assertGreater(sum(true_correct) / len(true_correct), 0.3)

            # Yet their naive credit overlaps: some worthless memories score
            # above some genuinely valuable ones.
            self.assertGreater(
                max(distractors),
                min(correct),
                "naive credit separates worthless from valuable memories cleanly, "
                "so the designed confound is absent and H1 would test nothing",
            )
        finally:
            result.close()


class TestWorldV2(unittest.TestCase):
    """The changes that make a forgetting experiment possible (prereg h2 §2)."""

    def test_partial_coverage_leaves_symptoms_uncovered(self) -> None:
        config = WorldConfig(coverage=0.5, n_correct_claims=20, n_wrong_claims=30)
        result = run(RunConfig(n_episodes=60, seed=0, epsilon=0.2, world=config))
        try:
            covered = {
                s.symptom
                for s in result.seeded
                if s.kind == CLAIM
                and s.action == result.world.rules[s.symptom].correct_action
            }
            self.assertLess(len(covered), len(result.world.symptoms))
            self.assertGreater(len(covered), 0)
        finally:
            result.close()

    def test_harm_bites_under_partial_coverage(self) -> None:
        """The P4 world gave every symptom a correct claim, so wrong claims were
        ranked below one and never followed — median true value -0.013. H2 is
        about forgetting harmful memories, so harm has to be real."""
        config = WorldConfig(coverage=0.5, n_correct_claims=20, n_wrong_claims=30)
        result = run(RunConfig(n_episodes=1500, seed=0, epsilon=0.2, world=config))
        try:
            truth = ground_truth(result)
            harmful = [
                truth[s.memory_id]
                for s in result.seeded
                if s.memory_id in truth
                and s.kind == CLAIM
                and s.action != result.world.rules[s.symptom].correct_action
            ]
            self.assertTrue(harmful)
            strongly_harmful = [v for v in harmful if v < -0.05]
            self.assertGreater(
                len(strongly_harmful) / len(harmful),
                0.25,
                "wrong claims are still mostly inert; the forgetting experiment "
                "would have nothing to forget",
            )
        finally:
            result.close()

    def test_rare_symptoms_are_sampled_rarely(self) -> None:
        config = WorldConfig(rare_fraction=0.10, rare_rate=0.05)
        world = RuleWorld(config, random.Random(0))
        rng = random.Random(1)
        draws = [world.sample_symptom(rng) for _ in range(20000)]
        rare_share = sum(1 for d in draws if d in world.rare) / len(draws)
        self.assertTrue(world.rare)
        # 4 of 40 symptoms at 1/20th weight: about 4*0.05/(36 + 4*0.05) ~ 0.55%.
        self.assertLess(rare_share, 0.02)
        self.assertGreater(rare_share, 0.001)

    def test_drift_flips_the_requested_fraction(self) -> None:
        world = RuleWorld(WorldConfig(), random.Random(0))
        before = {s: r.correct_action for s, r in world.rules.items()}
        flipped = world.apply_drift(0.4, random.Random(2))

        self.assertEqual(len(flipped), int(round(0.4 * len(world.symptoms))))
        for symptom in flipped:
            self.assertNotEqual(world.rules[symptom].correct_action, before[symptom])
        for symptom in set(world.symptoms) - flipped:
            self.assertEqual(world.rules[symptom].correct_action, before[symptom])

    def test_drift_makes_existing_claims_wrong_without_editing_them(self) -> None:
        """Obsolescence: nothing about the memory changed, only the world."""
        config = WorldConfig(coverage=1.0, n_correct_claims=40)
        result = run(RunConfig(n_episodes=40, seed=0, epsilon=0.2, world=config))
        try:
            claim = next(
                s for s in result.seeded
                if s.kind == CLAIM
                and s.action == result.world.rules[s.symptom].correct_action
            )
            content_before = result.fabric.get(claim.memory_id).content
            result.world.apply_drift(1.0, random.Random(5))

            self.assertNotEqual(
                claim.action, result.world.rules[claim.symptom].correct_action
            )
            self.assertEqual(result.fabric.get(claim.memory_id).content, content_before)
        finally:
            result.close()

    def test_stated_importance_cannot_distinguish_right_from_wrong_claims(self) -> None:
        """An importance score correlated with correctness would hand the
        recency+importance baseline information no rater could have."""
        config = WorldConfig(coverage=0.5, n_correct_claims=20, n_wrong_claims=30)
        result = run(RunConfig(n_episodes=40, seed=0, epsilon=0.2, world=config))
        try:
            correct, wrong, distractor = [], [], []
            for seeded in result.seeded:
                importance = result.fabric.get(seeded.memory_id).context["importance"]
                if seeded.kind == DISTRACTOR:
                    distractor.append(importance)
                elif seeded.action == result.world.rules[seeded.symptom].correct_action:
                    correct.append(importance)
                else:
                    wrong.append(importance)

            mean = lambda xs: sum(xs) / len(xs)  # noqa: E731
            # Claims rate above distractors: a rater can see one asserts an action.
            self.assertGreater(mean(correct + wrong), mean(distractor) + 0.1)
            # But right and wrong claims are indistinguishable.
            self.assertAlmostEqual(mean(correct), mean(wrong), delta=0.05)
        finally:
            result.close()


if __name__ == "__main__":
    unittest.main()
