"""The experiment harnesses, run offline against a stubbed model.

This file exists because of the project's record. Three of four simulated
hypotheses were mis-operationalised, and every time the bug was in the harness
rather than in the system under test: H1's largest effect was a scoring bug,
H3's `full` arm was penalised by a round-trip the harness created, Phase A's
first oracle was too weak to be a ceiling, and Phase B's first smoke run
retrieved none of 126 imports. Only the last of those was a defect in the
product; the rest were measurement.

So the arms are exercised here without a model, and the assertions are about
*structure*: that an arm does what its name says, that the records it produces
could support the comparison it is in, and that the obvious ways a harness goes
wrong would fail a test. These do not replace the live runs — they are what makes
a live run worth its two hours.
"""

from __future__ import annotations

import math
import random
import unittest
from unittest.mock import patch

from experiments import depotworld as W
from experiments import phase_a, phase_a_prime, phase_b, phase_c, stats
from experiments.phase_a import Lesson


def corpus(truth: W.Truth, sites=W.SITES, poison_every: int | None = None) -> list[Lesson]:
    """A corpus with no model in it, in the shape `write_corpus` produces.

    A poisoned lesson asserts an action that **no site's answer for that fault
    uses** — neither the base nor the exception. Otherwise the stub model's
    answer can coincide with the poisoning, blame withdraws only poisoned
    lessons, and the test for "does this rule destroy correct memory?" passes
    for entirely the wrong reason. It did, until this was fixed.
    """
    lessons: list[Lesson] = []
    position = 0
    for fault in W.FAULTS:
        used = {truth.base[fault], truth.exception_action[fault]}
        third = next(a for a in W.ACTIONS if a not in used)
        for site in sites:
            correct = truth.action(fault, site)
            # Poison every Nth *lesson*, not every Nth fault. Poisoning a whole
            # fault leaves no correct lesson about it anywhere, so a withdrawal
            # rule has nothing correct left to destroy and the test that checks
            # for exactly that silently measures nothing.
            poisoned = poison_every is not None and position % poison_every == 0
            position += 1
            asserted = third if poisoned else correct
            lessons.append(
                Lesson(
                    content=f"For {fault} at {site} sites, {asserted} resolves it.",
                    fault=fault, site=site, asserted=asserted, poisoned=poisoned,
                )
            )
    return lessons


def wrong_answerer(truth: W.Truth):
    """A model that never gets it right, so every episode fails and every
    withdrawal rule fires as hard as it can.

    On an exception episode it answers the fault's **base** action — wrong here,
    correct at the other two sites. That detail matters: a stub that always
    answered the same action the poisoning uses would make blame withdraw only
    poisoned lessons, and the test for "does it destroy correct memory?" would
    pass for the wrong reason.
    """

    def ask(client, model, memory_text, episode):
        if episode.is_exception:
            answer = truth.base[episode.fault]
        else:
            answer = truth.exception_action[episode.fault]
        if answer == episode.correct:
            answer = next(a for a in W.ACTIONS if a != episode.correct)
        return answer, 10.0, 1.0

    return ask


def always_right(client, model, memory_text, episode):
    return episode.correct, 10.0, 1.0


class TestReleaseSchedule(unittest.TestCase):
    def test_the_store_fills_over_the_run(self) -> None:
        """Long-horizon degradation is only measurable if the corpus grows; a
        flat schedule would make that metric a constant."""
        schedule = phase_a.release_schedule(18, 24)
        self.assertEqual(len(schedule), 24)
        self.assertLess(schedule[0], schedule[-1])
        self.assertEqual(schedule[-1], 18)
        self.assertEqual(schedule, sorted(schedule))

    def test_it_never_exceeds_the_corpus(self) -> None:
        for count in (1, 5, 18, 40):
            schedule = phase_a.release_schedule(count, 12)
            self.assertLessEqual(max(schedule), count)
            self.assertGreaterEqual(min(schedule), 1)


class TestPhaseAArms(unittest.TestCase):
    def setUp(self) -> None:
        self.rng = random.Random(0)
        self.truth = W.build_truth(self.rng)
        self.lessons = corpus(self.truth, poison_every=3)
        self.episodes = W.eval_episodes(self.truth, self.rng, count=12)
        self.schedule = phase_a.release_schedule(len(self.lessons), len(self.episodes))
        self.always_wrong = wrong_answerer(self.truth)

    def _vector(self, arm, ask=None):
        ask = ask or self.always_wrong
        with patch.object(phase_a, "_ask", ask):
            return phase_a.run_vector_arm(
                arm, 0, self.lessons, self.episodes, self.schedule,
                None, None, "stub", verbose=False,
            )

    def test_local_rag_only_ever_shows_this_site(self) -> None:
        """The arm's whole definition. If it leaked other sites it would be
        `shared_memory` under another name, and Phase A's headline comparison
        would be between two copies of the same thing."""
        result = self._vector("local_rag")
        for decision, episode in zip(result.decisions, self.episodes):
            for content in decision.shown:
                lesson = next(l for l in self.lessons if l.content == content)
                self.assertEqual(lesson.site, episode.site)

    def test_shared_memory_does_show_other_sites(self) -> None:
        result = self._vector("shared_memory")
        sites = {
            next(l for l in self.lessons if l.content == c).site
            for d in result.decisions for c in d.shown
        }
        self.assertGreater(len(sites), 1, "pooling never pooled anything")

    def test_decay_withdraws_and_shared_memory_does_not(self) -> None:
        """With a model that always fails, the decay arm must end up showing
        strictly less than the arm that withdraws nothing."""
        decay = self._vector("shared_memory_decay")
        pooled = self._vector("shared_memory")
        self.assertLess(
            sum(len(d.shown) for d in decay.decisions),
            sum(len(d.shown) for d in pooled.decisions),
        )

    def test_a_perfect_model_leaves_the_decay_arm_intact(self) -> None:
        """The other direction: nothing fails, so nothing is withdrawn, and the
        decay arm must be indistinguishable from the pooled one. A harness that
        pruned regardless of outcome would pass the previous test and fail this.
        """
        decay = self._vector("shared_memory_decay", ask=always_right)
        pooled = self._vector("shared_memory", ask=always_right)
        self.assertEqual(
            [len(d.shown) for d in decay.decisions],
            [len(d.shown) for d in pooled.decisions],
        )

    def test_the_oracle_never_shows_a_wrong_for_here_memory(self) -> None:
        """Phase A's first oracle was beaten by an ungoverned arm, which is a
        proof it was not a ceiling. The corrected one filters perfectly at the
        same k the other arms get."""
        with patch.object(phase_a, "_ask", self.always_wrong):
            result = phase_a.run_simple_arm(
                "oracle", 0, self.lessons, self.episodes, self.schedule,
                None, "stub", embedder=None, verbose=False,
            )
        for decision, episode in zip(result.decisions, self.episodes):
            self.assertEqual(decision.shown_wrong, 0)

    def test_the_oracle_gets_the_same_budget_as_the_arms_it_bounds(self) -> None:
        """The specific flaw in the first version: it showed one memory where
        every other arm showed three, so the ceiling was set by its retrieval
        budget rather than by the limits of selection."""
        with patch.object(phase_a, "_ask", self.always_wrong):
            oracle = phase_a.run_simple_arm(
                "oracle", 0, self.lessons, self.episodes, self.schedule,
                None, "stub", embedder=None, k=3, verbose=False,
            )
        self.assertTrue(any(len(d.shown) > 1 for d in oracle.decisions))

    def test_no_memory_shows_nothing(self) -> None:
        with patch.object(phase_a, "_ask", self.always_wrong):
            result = phase_a.run_simple_arm(
                "no_memory", 0, self.lessons, self.episodes, self.schedule,
                None, "stub", verbose=False,
            )
        self.assertTrue(all(d.shown == [] for d in result.decisions))

    def test_harm_is_attributed_not_merely_coincident(self) -> None:
        """`harmful` must require that a memory in context asserted the action
        taken. A wrong answer with no memory behind it is the model's own error
        and is not the memory layer's to own."""
        episode = self.episodes[0]
        wrong = next(a for a in W.ACTIONS if a != episode.correct)
        unrelated = next(
            a for a in W.ACTIONS if a not in (episode.correct, wrong)
        )
        lesson = Lesson(
            content="x", fault=episode.fault, site=episode.site,
            asserted=unrelated, poisoned=True,
        )
        blamed = phase_a._score(
            "t", 0, 0, episode, [lesson], wrong, 0.0, 0.0, 0.0, store_size=1
        )
        self.assertFalse(blamed.success)
        self.assertFalse(blamed.harmful, "harm was attributed to an unrelated memory")

        lesson_that_said_it = Lesson(
            content="y", fault=episode.fault, site=episode.site,
            asserted=wrong, poisoned=True,
        )
        owned = phase_a._score(
            "t", 0, 0, episode, [lesson_that_said_it], wrong,
            0.0, 0.0, 0.0, store_size=1,
        )
        self.assertTrue(owned.harmful)


class TestPhaseAPrimeArms(unittest.TestCase):
    def setUp(self) -> None:
        self.rng = random.Random(1)
        self.truth = W.build_truth(self.rng)
        self.lessons = corpus(self.truth, poison_every=3)
        self.episodes = W.eval_episodes(self.truth, self.rng, count=8)
        self.schedule = phase_a_prime.release_schedule(
            len(self.lessons), len(self.episodes)
        )
        self.always_wrong = wrong_answerer(self.truth)

    def _run(self, arm, ask=None):
        ask = ask or self.always_wrong
        with patch.object(phase_a_prime, "_ask", ask), \
             patch.object(phase_a, "_ask", ask):
            return phase_a_prime.run_arm(
                arm, 0, self.lessons, self.episodes, self.schedule,
                None, None, "stub", verbose=False,
            )

    def test_blame_withdraws_far_more_than_leave_one_out(self) -> None:
        """The registered comparison. Blame fires on surface agreement, so with
        a model that always fails it withdraws something almost every episode;
        leave-one-out fires only on a counterfactual."""
        blame = self._run("fabric_blame")
        loo = self._run("fabric_loo")
        self.assertGreater(len(blame.withdrawals), len(loo.withdrawals))

    def test_leave_one_out_pays_for_itself_in_calls(self) -> None:
        """Its cost is a registered result, so the harness has to count it."""
        loo = self._run("fabric_loo")
        self.assertGreater(loo.extra_calls, 0)
        blame = self._run("fabric_blame")
        self.assertEqual(blame.extra_calls, 0)

    def test_leave_one_out_withdraws_nothing_when_removal_does_not_help(self) -> None:
        """With a model that is wrong whatever it is shown, no counterfactual
        succeeds, so a correct leave-one-out must withdraw nothing at all. This
        is the test that separates real attribution from blame wearing its
        name."""
        def wrong_regardless(client, model, memory_text, episode):
            return next(a for a in W.ACTIONS if a != episode.correct), 10.0, 1.0

        loo = self._run("fabric_loo", ask=wrong_regardless)
        self.assertEqual(len(loo.withdrawals), 0)

    def test_withdrawals_record_whether_the_memory_was_correct(self) -> None:
        """PA'2's second condition needs this split, and Phase A only found the
        over-pruning mechanism by looking at it."""
        blame = self._run("fabric_blame")
        self.assertTrue(blame.withdrawals)
        self.assertTrue(any(w.was_correct for w in blame.withdrawals))
        for w in blame.withdrawals:
            self.assertIn(w.arm, phase_a_prime.WITHDRAWING)
            self.assertTrue(w.reason)

    def test_the_baseline_withdraws_nothing_ever(self) -> None:
        with patch.object(phase_a_prime, "_ask", self.always_wrong):
            base = phase_a_prime.run_vector_baseline(
                0, self.lessons, self.episodes, self.schedule,
                None, None, "stub", verbose=False,
            )
        self.assertEqual(len(base.withdrawals), 0)


class TestPhaseBArms(unittest.TestCase):
    def setUp(self) -> None:
        self.rng = random.Random(2)
        self.truth = W.build_truth(self.rng)
        self.corpora = {
            agent: corpus(self.truth, sites=sites, poison_every=3)
            for agent, sites in phase_b.TERRITORIES.items()
        }
        self.episodes = phase_b.agent_episodes(self.truth, self.rng, 4)
        self.always_wrong = wrong_answerer(self.truth)

    def _run(self, arm, ask=None):
        ask = ask or self.always_wrong
        with patch.object(phase_b, "_ask", ask):
            return phase_b.run_arm(
                arm, 0, self.truth, self.corpora, self.episodes, None, None,
                "stub", verbose=False,
            )

    def test_isolated_shares_nothing(self) -> None:
        self.assertEqual(self._run("isolated").imports, 0)

    def test_share_all_shares_and_the_imports_reach_a_prompt(self) -> None:
        """The regression that made Phase B's first smoke run meaningless: 126
        imports were accepted and not one reached a prompt, because ranking on
        value fell through to creation time and imports are always newer."""
        result = self._run("share_all")
        self.assertGreater(result.imports, 0)
        self.assertGreater(
            sum(d.shown_imported for d in result.decisions), 0,
            "imports were accepted but never retrieved",
        )

    def test_overlap_sharing_sends_less_than_sharing_everything(self) -> None:
        self.assertLess(self._run("share_overlap").imports,
                        self._run("share_all").imports)

    def test_the_oracle_shares_nothing_wrong(self) -> None:
        """It fixes the ceiling, so an import it accepted that is wrong for the
        recipient would make the ceiling unreachable in the wrong direction."""
        result = self._run("oracle_share")
        self.assertEqual(result.imports_wrong, 0)
        self.assertGreater(result.imports, 0)

    def test_the_oracle_never_shares_what_could_mislead_the_recipient(self) -> None:
        """The test that was missing, and the bug it would have caught.

        The first version shared a memory that was correct at *its own* site.
        A recipient works several sites, so a lesson correct for `cold_store`
        reached `north` and then misled it on every urban episode. The arm was
        beatable by construction — it scored below `share_overlap_propagate` on
        both seeds that ran, while reporting zero wrong imports and 10% negative
        transfer, which cannot both be true.

        A ceiling has to be unbeatable in principle, so the condition is that
        every memory it sends is correct at *every* site its recipient works.
        """
        for recipient, sites in phase_b.TERRITORIES.items():
            for sender, lessons in self.corpora.items():
                if sender == recipient:
                    continue
                for lesson in lessons:
                    allowed = phase_b._should_share(
                        "oracle_share", lesson, recipient, False,
                        all(
                            lesson.asserted == self.truth.action(lesson.fault, s)
                            for s in sites
                        ),
                    )
                    if not allowed:
                        continue
                    for site in sites:
                        self.assertEqual(
                            lesson.asserted,
                            self.truth.action(lesson.fault, site),
                            f"oracle sent {sender}'s {lesson.fault}/{lesson.site} "
                            f"lesson to {recipient}, where it is wrong at {site}",
                        )

    def test_propagation_acts_and_the_plain_arm_does_not(self) -> None:
        self.assertGreater(self._run("share_all_propagate").propagated, 0)
        self.assertEqual(self._run("share_all").propagated, 0)

    def test_every_agent_only_works_its_own_sites(self) -> None:
        """A federation where an agent is quizzed on a territory it does not
        hold would measure something else entirely."""
        for agent, sites in phase_b.TERRITORIES.items():
            for episode in self.episodes[agent]:
                self.assertIn(episode.site, sites)

    def test_negative_transfer_requires_an_imported_memory(self) -> None:
        """It is the harm attributable to federation specifically. If a native
        memory could trigger it, the metric would not separate federation's
        damage from the agent's own."""
        isolated = self._run("isolated")
        self.assertTrue(all(not d.negative_transfer for d in isolated.decisions))

    def test_per_agent_results_are_reported_separately(self) -> None:
        """PB1 requires the worst agent not to get worse, so a mean alone cannot
        answer it."""
        result = self._run("share_all")
        per = result.per_agent()
        self.assertEqual(set(per), set(phase_b.AGENTS))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()


class TestPhaseCArms(unittest.TestCase):
    """The population arms, and the two statistics the ecology claim rests on."""

    def setUp(self) -> None:
        self.rng = random.Random(3)
        self.truth = W.build_truth(self.rng)
        self.corpora = {
            agent: corpus(self.truth, sites=sites, poison_every=4)
            for agent, sites in phase_c.TERRITORIES.items()
        }
        self.episodes = phase_c.agent_episodes(self.truth, self.rng, 6)

    def _realistic(self, client, model, memory_text, episode):
        """Succeeds when a correct memory is in front of it, fails otherwise —
        which is what the live runs measured at roughly 95% conversion. A stub
        that always fails would leave the learner with nothing but failures and
        no edges to form, so it could not test the learner at all."""
        shown = memory_text.replace("_", " ")
        if episode.correct in memory_text or episode.correct.replace("_", " ") in shown:
            return episode.correct, 10.0, 1.0
        return next(a for a in W.ACTIONS if a != episode.correct), 10.0, 1.0

    def _run(self, arm):
        with patch.object(phase_c, "_ask", self._realistic):
            return phase_c.run_arm(
                arm, 0, self.corpora, self.episodes, None, None, "stub",
                verbose=False,
            )

    def test_isolated_shares_nothing(self) -> None:
        self.assertEqual(self._run("isolated").imports, 0)

    def test_the_oracle_shares_nothing_wrong(self) -> None:
        result = self._run("oracle_share")
        self.assertGreater(result.imports, 0)
        self.assertEqual(result.imports_wrong, 0)

    def test_imports_reach_prompts(self) -> None:
        """Phase B's regression, guarded here too: accepting imports that no
        agent ever retrieves makes every sharing comparison meaningless."""
        result = self._run("share_all")
        self.assertGreater(sum(d.shown_imported for d in result.decisions), 0)

    def test_the_learner_forms_a_sharing_graph(self) -> None:
        result = self._run("learned")
        edges = sum(len(v) for v in result.learned_edges.values())
        self.assertGreater(edges, 0, "the learner never learned an edge")

    def test_a_fixed_policy_has_no_learned_graph(self) -> None:
        self.assertEqual(self._run("share_all").learned_edges, {})

    def test_the_outcome_channel_changes_what_is_learned(self) -> None:
        """`learned` is fed the recipient's verified outcome; its blind twin is
        fed only the sender's own. If the two produced identical graphs the
        channel would be doing nothing and the arm comparison could not detect
        it."""
        seeing = self._run("learned").learned_edges
        blind = self._run("learned_no_feedback").learned_edges
        self.assertNotEqual(seeing, blind)

    def test_the_bandit_prefers_a_recipient_that_succeeds(self) -> None:
        bandit = phase_c.RecipientBandit(random.Random(0))
        for _ in range(10):
            bandit.record("a1", "a2", True)
            bandit.record("a1", "a3", False)
        self.assertGreater(bandit.rate("a1", "a2"), bandit.rate("a1", "a3"))
        self.assertIn("a2", bandit.edges()["a1"])
        self.assertNotIn("a3", bandit.edges()["a1"])

    def test_an_untried_recipient_starts_optimistic(self) -> None:
        """Otherwise the population freezes on whoever it happened to try
        first, and the learner is measuring its own initialisation."""
        bandit = phase_c.RecipientBandit(random.Random(0))
        self.assertEqual(bandit.rate("a1", "a2"), 1.0)

    def test_spearman_handles_ties_and_degenerate_input(self) -> None:
        self.assertAlmostEqual(phase_c.spearman([1, 2, 3, 4], [1, 2, 3, 4]), 1.0)
        self.assertAlmostEqual(phase_c.spearman([1, 2, 3, 4], [4, 3, 2, 1]), -1.0)
        self.assertTrue(math.isnan(phase_c.spearman([1, 1, 1], [5, 5, 5])))
        self.assertTrue(math.isnan(phase_c.spearman([1], [1])))

    def test_an_undefined_correlation_is_not_reported_as_a_weak_one(self) -> None:
        """Under `share_all` every memory reaches every store, so spread has no
        variance and there is nothing for value to correlate with. That is an
        opposite finding to "no relationship found", and a bare NaN reads as
        the second."""
        said = phase_c.describe_rho(float("nan"), 20, [8.0] * 20)
        self.assertIn("undefined", said)
        self.assertIn("every store", said)

    def test_the_true_overlap_graph_is_what_the_learner_is_scored_against(self) -> None:
        self.assertEqual(phase_c.neighbourhood_match(phase_c.overlap_graph()), 1.0)
        self.assertEqual(
            phase_c.neighbourhood_match({a: set() for a in phase_c.AGENTS}), 0.0
        )

    def test_every_agent_only_works_its_own_sites(self) -> None:
        for agent, sites in phase_c.TERRITORIES.items():
            for episode in self.episodes[agent]:
                self.assertIn(episode.site, sites)


class TestCeilingCheckIsMechanical(unittest.TestCase):
    """AGENTS.md principle 8b, enforced rather than remembered.

    This project built a mis-specified ceiling three times — H3's threshold
    exceeded its own, Phase A's oracle got a smaller retrieval budget than the
    arms it bounded, and Phase B's oracle poisoned its own recipients. Principle
    8a made the ceiling mandatory after the first and did not prevent the next
    two, because "is the ceiling actually a ceiling?" was left to whoever was
    reading the output.
    """

    def test_an_arm_above_the_ceiling_is_reported(self) -> None:
        problems = stats.check_ceiling(
            {"baseline": 0.50, "contender": 0.90, "oracle": 0.80}, "oracle"
        )
        self.assertEqual(len(problems), 1)
        self.assertIn("contender", problems[0])
        self.assertIn("8b", problems[0])

    def test_it_names_both_possibilities(self) -> None:
        """A small excess can be sampling noise. The message must not assert
        which it is, because dismissing it was the mistake in Phase B — the
        ordering looked like noise and the real tell was a contradiction
        elsewhere."""
        problems = stats.check_ceiling({"a": 0.81, "oracle": 0.80}, "oracle")
        self.assertIn("noise", problems[0])
        self.assertIn("mis-specified", problems[0])

    def test_a_sound_ceiling_passes_quietly(self) -> None:
        self.assertEqual(
            stats.check_ceiling({"a": 0.50, "b": 0.79, "oracle": 0.80}, "oracle"), []
        )

    def test_a_tie_is_not_a_failure(self) -> None:
        """An arm reaching the ceiling means the ceiling is attainable, which is
        a finding rather than a fault."""
        self.assertEqual(
            stats.check_ceiling({"a": 0.80, "oracle": 0.80}, "oracle"), []
        )

    def test_a_missing_ceiling_arm_is_itself_a_problem(self) -> None:
        problems = stats.check_ceiling({"a": 0.5}, "oracle")
        self.assertEqual(len(problems), 1)
        self.assertIn("no ceiling arm", problems[0])

    def test_every_phase_runs_the_check(self) -> None:
        """The point is that it cannot be forgotten. If a phase's verdict stops
        calling it, this fails."""
        import inspect

        for module, ceiling in (
            (phase_a, "oracle"),
            (phase_a_prime, "oracle"),
            (phase_b, "oracle_share"),
            (phase_c, "oracle_share"),
        ):
            source = inspect.getsource(module.verdict)
            self.assertIn("report_ceiling", source, module.__name__)
            self.assertIn(ceiling, source, module.__name__)
