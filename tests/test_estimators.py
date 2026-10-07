"""Known-answer tests for value estimation.

The central test here is `test_naive_is_fooled_by_selection_bias_and_ips_is_not`.
It builds a world where a memory has *exactly zero* true effect but is retrieved
mostly on easy tasks, and checks that the naive estimator reports it as excellent
while the propensity-corrected estimator reports approximately nothing.

That is the whole thesis in one test (CRITICAL_REVIEW section 2.2). If it ever
stops passing, the machinery has stopped doing the one thing it exists to do.
"""

from __future__ import annotations

import math
import random
import unittest

from memory_fabric import events as ev
from memory_fabric.estimators import (
    AmortizedEstimator,
    DoublyRobustEstimator,
    IPSEstimator,
    NaiveUsageEstimator,
    _wilson_interval,
)
from memory_fabric.eventlog import EventLog
from memory_fabric.projections import Projection

EASY_OUTCOME = 0.9
HARD_OUTCOME = 0.3
P_EXPOSE_EASY = 0.9
P_EXPOSE_HARD = 0.1


def build_confounded_world(
    n_episodes: int = 4000, seed: int = 0, memory_effect: float = 0.0
) -> Projection:
    """A memory that is retrieved on easy tasks and does nothing.

    The logging policy exposes it with probability 0.9 on easy tasks and 0.1 on
    hard ones. Easy tasks score higher whether or not the memory is present, so
    a naive average over exposures inherits the task difficulty, not the memory's
    contribution.
    """
    rng = random.Random(seed)
    log = EventLog(":memory:")
    projection = Projection()

    def emit(event):
        for stored in log.append_many([event]):
            projection.apply(stored)

    for index in range(n_episodes):
        episode_id = f"ep{index}"
        easy = index % 2 == 0
        base = EASY_OUTCOME if easy else HARD_OUTCOME
        p_expose = P_EXPOSE_EASY if easy else P_EXPOSE_HARD

        emit(
            ev.episode_started(
                ts=index,
                agent_id="agent-a",
                episode_id=episode_id,
                task_id="easy" if easy else "hard",
                context={"difficulty": "easy" if easy else "hard"},
                seed=index,
            )
        )

        exposed = rng.random() < p_expose
        emit(
            ev.exposure_decided(
                ts=index,
                agent_id="agent-a",
                episode_id=episode_id,
                memory_id="M",
                version=1,
                exposed=exposed,
                propensity=p_expose if exposed else 1.0 - p_expose,
                policy_id="synthetic",
            )
        )

        outcome = base + (memory_effect if exposed else 0.0)
        emit(
            ev.outcome_recorded(
                ts=index, episode_id=episode_id, outcome=outcome, verifier_id="env"
            )
        )

    log.close()
    return projection


def build_population(
    n_memories: int = 24, n_episodes: int = 1200, seed: int = 0
) -> Projection:
    """A store with many memories of differing true value.

    Needed for amortization, which learns from the population: with a single
    memory there is nothing to borrow strength from, and declining is the right
    answer rather than a bug.
    """
    from memory_fabric.model import Memory, MemoryType, Provenance

    rng = random.Random(seed)
    log = EventLog(":memory:")
    projection = Projection()

    def emit(event):
        for stored in log.append_many([event]):
            projection.apply(stored)

    effects = {}
    easy_biased = {}
    for index in range(n_memories):
        memory_id = f"M{index}"
        effects[memory_id] = rng.choice([-0.3, -0.1, 0.0, 0.1, 0.3])
        # Half the memories are retrieved mainly on easy tasks, which is the
        # confound: their observed success rate reflects the tasks they landed
        # on, not what they contributed.
        easy_biased[memory_id] = index % 2 == 0
        emit(
            ev.memory_created(
                ts=0,
                memory=Memory(
                    id=memory_id,
                    version=1,
                    type=MemoryType.SEMANTIC,
                    content=f"memory {index}",
                    provenance=Provenance(created_by="seeder"),
                ),
            )
        )

    ids = list(effects)
    for index in range(n_episodes):
        episode_id = f"ep{index}"
        emit(
            ev.episode_started(
                ts=index, agent_id="a", episode_id=episode_id,
                task_id="t", context={}, seed=index,
            )
        )
        easy = rng.random() < 0.5
        outcome = 0.8 if easy else 0.3
        for memory_id in rng.sample(ids, 3):
            if easy_biased[memory_id]:
                p_expose = 0.9 if easy else 0.1
            else:
                p_expose = 0.5
            exposed = rng.random() < p_expose
            emit(
                ev.exposure_decided(
                    ts=index, agent_id="a", episode_id=episode_id,
                    memory_id=memory_id, version=1, exposed=exposed,
                    propensity=p_expose if exposed else 1 - p_expose,
                    policy_id="synthetic",
                )
            )
            if exposed:
                outcome += effects[memory_id]
        outcome = min(max(outcome + rng.uniform(-0.05, 0.05), 0.0), 1.0)
        emit(ev.outcome_recorded(ts=index, episode_id=episode_id,
                                 outcome=outcome, verifier_id="env"))

    log.close()
    projection.effects = effects  # type: ignore[attr-defined]
    return projection


class TestSelectionBias(unittest.TestCase):
    def test_naive_is_fooled_by_selection_bias_and_ips_is_not(self) -> None:
        projection = build_confounded_world(memory_effect=0.0)
        state = projection.state

        naive = NaiveUsageEstimator()
        naive.fit(state)
        naive_estimate = naive.estimate("M")

        ips = IPSEstimator()
        ips.fit(state)
        ips_estimate = ips.estimate("M")

        # The memory looks excellent: most episodes where it appeared went well.
        # The population mean is 0.6, so anything near 0.84 is an illusion
        # manufactured entirely by which tasks it was retrieved on.
        self.assertGreater(naive_estimate.mean, 0.80)

        # Its true effect is zero, and the corrected estimator recovers that.
        self.assertAlmostEqual(ips_estimate.mean, 0.0, delta=0.05)
        self.assertLess(ips_estimate.ci_low, 0.0)
        self.assertGreater(ips_estimate.ci_high, 0.0)

    def test_ips_recovers_a_real_positive_effect(self) -> None:
        """The correction must not simply shrink everything to zero."""
        projection = build_confounded_world(memory_effect=0.2)
        ips = IPSEstimator()
        ips.fit(projection.state)
        estimate = ips.estimate("M")
        self.assertAlmostEqual(estimate.mean, 0.2, delta=0.05)
        self.assertGreater(estimate.ci_low, 0.0)
        self.assertTrue(estimate.shows_benefit)

    def test_ips_recovers_a_harmful_effect(self) -> None:
        projection = build_confounded_world(memory_effect=-0.25)
        ips = IPSEstimator()
        ips.fit(projection.state)
        estimate = ips.estimate("M")
        self.assertAlmostEqual(estimate.mean, -0.25, delta=0.05)
        self.assertLess(estimate.ci_high, 0.0)
        self.assertFalse(estimate.shows_benefit)

        # The naive estimator gives no hint of harm. Easy tasks still mostly
        # succeed even after a 0.25 penalty, so the memory scores around 0.58:
        # above the neutral 0.5 prior and close to the 0.6 population average,
        # which is to say entirely unremarkable. Nothing in that number would
        # ever trigger a review, while the corrected estimate above rules out
        # any benefit outright.
        naive = NaiveUsageEstimator()
        naive.fit(projection.state)
        naive_estimate = naive.estimate("M")
        self.assertGreater(naive_estimate.mean, 0.5)
        self.assertGreater(naive_estimate.ci_high, 0.5)
        # Ranking on the naive score cannot separate a harmful memory from an
        # average one, which is the failure the contrastive flag guards against.
        self.assertFalse(naive_estimate.shows_benefit)


class TestDoublyRobust(unittest.TestCase):
    """DR should match IPS on the answer and beat it on the variance."""

    def test_recovers_zero_effect_under_confounding(self) -> None:
        projection = build_confounded_world(memory_effect=0.0)
        dr = DoublyRobustEstimator()
        dr.fit(projection.state)
        estimate = dr.estimate("M")
        self.assertAlmostEqual(estimate.mean, 0.0, delta=0.05)
        self.assertTrue(estimate.contrastive)

    def test_recovers_a_real_effect(self) -> None:
        for effect in (0.2, -0.25):
            with self.subTest(effect=effect):
                projection = build_confounded_world(memory_effect=effect)
                dr = DoublyRobustEstimator()
                dr.fit(projection.state)
                self.assertAlmostEqual(dr.estimate("M").mean, effect, delta=0.05)

    def test_narrower_intervals_than_plain_ips(self) -> None:
        """The outcome model absorbs the variation the task explains, so the
        IPS term only has to correct what the model missed."""
        projection = build_confounded_world(n_episodes=1500, memory_effect=0.2)
        ips, dr = IPSEstimator(), DoublyRobustEstimator()
        ips.fit(projection.state)
        dr.fit(projection.state)
        ips_width = ips.estimate("M").ci_high - ips.estimate("M").ci_low
        dr_width = dr.estimate("M").ci_high - dr.estimate("M").ci_low
        self.assertLess(dr_width, ips_width)

    def test_refuses_without_overlap(self) -> None:
        projection = build_confounded_world(n_episodes=200)
        for record in projection.state.exposures:
            record.exposed = True  # one arm only
        dr = DoublyRobustEstimator()
        dr.fit(projection.state)
        self.assertEqual(dr.estimate("M").estimator, "none")


class TestAmortized(unittest.TestCase):
    def test_keeps_its_own_estimate_when_evidence_is_plentiful(self) -> None:
        projection = build_confounded_world(n_episodes=3000, memory_effect=0.2)
        amortized = AmortizedEstimator()
        amortized.fit(projection.state)
        self.assertAlmostEqual(amortized.estimate("M").mean, 0.2, delta=0.08)

    def test_answers_for_a_memory_with_no_evidence_of_its_own(self) -> None:
        """The whole point of amortization: a memory with no comparison group
        still gets the population's view of memories like it, marked as resting
        on nothing so nothing treats it as proven."""
        projection = build_population()
        state = projection.state
        state.memories["ghost"] = _ghost_memory()

        amortized = AmortizedEstimator()
        amortized.fit(state)
        estimate = amortized.estimate("ghost")

        self.assertEqual(estimate.n_eff, 0.0)
        self.assertNotEqual(estimate.estimator, "none")
        self.assertTrue(math.isfinite(estimate.mean))

        # The base estimator, having no comparison group, declines outright.
        base = DoublyRobustEstimator()
        base.fit(state)
        self.assertEqual(base.estimate("ghost").estimator, "none")

    def test_declines_when_there_is_no_population_to_learn_from(self) -> None:
        """One memory is not a population; predicting from it would be
        inventing evidence rather than borrowing it."""
        projection = build_confounded_world(n_episodes=400, memory_effect=0.2)
        projection.state.memories["ghost"] = _ghost_memory()
        amortized = AmortizedEstimator()
        amortized.fit(projection.state)
        self.assertEqual(amortized.estimate("ghost").estimator, "none")

    def test_ranks_a_population_better_than_the_naive_baseline(self) -> None:
        from experiments.stats import spearman

        projection = build_population()
        effects = projection.effects  # type: ignore[attr-defined]
        ids = sorted(effects)

        amortized = AmortizedEstimator()
        amortized.fit(projection.state)
        naive = NaiveUsageEstimator()
        naive.fit(projection.state)

        truth = [effects[m] for m in ids]
        rho_amortized = spearman([amortized.estimate(m).mean for m in ids], truth)
        rho_naive = spearman([naive.estimate(m).mean for m in ids], truth)
        self.assertGreater(rho_amortized, rho_naive)

    def test_shrinkage_does_not_narrow_the_interval(self) -> None:
        """Borrowing strength is not the same as having gathered evidence."""
        projection = build_confounded_world(n_episodes=600, memory_effect=0.2)
        base = DoublyRobustEstimator()
        base.fit(projection.state)
        amortized = AmortizedEstimator()
        amortized.fit(projection.state)

        own = base.estimate("M")
        shrunk = amortized.estimate("M")
        self.assertAlmostEqual(
            shrunk.ci_high - shrunk.ci_low, own.ci_high - own.ci_low, places=6
        )

    def test_is_contrastive(self) -> None:
        projection = build_confounded_world(n_episodes=400, memory_effect=0.1)
        amortized = AmortizedEstimator()
        amortized.fit(projection.state)
        self.assertTrue(amortized.estimate("M").contrastive)


def _ghost_memory():
    from memory_fabric.model import Memory, MemoryType, Provenance

    return Memory(
        id="ghost",
        version=1,
        type=MemoryType.SEMANTIC,
        content="never exposed",
        provenance=Provenance(created_by="a"),
    )


class TestEstimatorContracts(unittest.TestCase):
    def test_naive_is_not_contrastive_and_ips_is(self) -> None:
        projection = build_confounded_world(n_episodes=200)
        naive = NaiveUsageEstimator()
        naive.fit(projection.state)
        ips = IPSEstimator()
        ips.fit(projection.state)

        self.assertFalse(naive.estimate("M").contrastive)
        self.assertTrue(ips.estimate("M").contrastive)

        # A non-contrastive estimate can never claim benefit, whatever its mean.
        self.assertFalse(naive.estimate("M").shows_benefit)

    def test_ips_refuses_to_answer_without_overlap(self) -> None:
        """A deterministic logging policy yields no causal conclusion.

        This is the honest failure mode: the estimator says "unknown" rather
        than returning a number computed from one arm.
        """
        log = EventLog(":memory:")
        projection = Projection()

        def emit(event):
            for stored in log.append_many([event]):
                projection.apply(stored)

        for index in range(500):
            episode_id = f"ep{index}"
            emit(
                ev.episode_started(
                    ts=index,
                    agent_id="a",
                    episode_id=episode_id,
                    task_id="t",
                    context={},
                    seed=None,
                )
            )
            emit(
                ev.exposure_decided(
                    ts=index,
                    agent_id="a",
                    episode_id=episode_id,
                    memory_id="M",
                    version=1,
                    exposed=True,  # always exposed: no withheld arm exists
                    propensity=1.0,
                    policy_id="top_k",
                )
            )
            emit(ev.outcome_recorded(ts=index, episode_id=episode_id, outcome=1.0, verifier_id="env"))

        ips = IPSEstimator()
        ips.fit(projection.state)
        estimate = ips.estimate("M")
        self.assertEqual(estimate.n_eff, 0.0)
        self.assertEqual(estimate.estimator, "none")
        log.close()

    def test_episodes_without_verified_outcomes_are_excluded(self) -> None:
        log = EventLog(":memory:")
        projection = Projection()

        def emit(event):
            for stored in log.append_many([event]):
                projection.apply(stored)

        emit(
            ev.episode_started(
                ts=1, agent_id="a", episode_id="ep1", task_id="t", context={}, seed=None
            )
        )
        emit(
            ev.exposure_decided(
                ts=1,
                agent_id="a",
                episode_id="ep1",
                memory_id="M",
                version=1,
                exposed=True,
                propensity=0.5,
                policy_id="p",
            )
        )
        # No OutcomeRecorded for ep1.

        naive = NaiveUsageEstimator()
        naive.fit(projection.state)
        self.assertEqual(naive.estimate("M").n_eff, 0.0)
        log.close()

    def test_unknown_memory_returns_the_prior(self) -> None:
        projection = build_confounded_world(n_episodes=50)
        naive = NaiveUsageEstimator(prior_mean=0.5)
        naive.fit(projection.state)
        estimate = naive.estimate("does-not-exist")
        self.assertEqual(estimate.mean, 0.5)
        self.assertEqual(estimate.n_eff, 0.0)


class TestExposureIndex(unittest.TestCase):
    """The index that keeps listings from being quadratic in the store.

    Scanning every exposure record inside `estimate` made a dashboard listing
    walk the whole log once per row. These assert the grouping is built in `fit`
    and is correct, without depending on wall-clock timing.
    """

    def test_estimates_come_from_the_snapshot_taken_at_fit(self) -> None:
        projection = build_confounded_world(n_episodes=400, memory_effect=0.2)
        ips = IPSEstimator()
        ips.fit(projection.state)
        before = ips.estimate("M").mean

        # Appending to the live list must not change an estimate, which it would
        # if `estimate` were rescanning rather than reading a prepared index.
        projection.state.exposures.extend(projection.state.exposures[:50])
        self.assertEqual(ips.estimate("M").mean, before)

        # Refitting picks the new data up, so nothing is stale by accident.
        ips.fit(projection.state)
        self.assertIsInstance(ips.estimate("M").mean, float)

    def test_index_groups_by_memory(self) -> None:
        from memory_fabric.estimators import build_exposure_index

        projection = build_confounded_world(n_episodes=100)
        index = build_exposure_index(projection.state)
        self.assertEqual(set(index), {"M"})
        self.assertTrue(all(r.memory_id == "M" for r, _, _ in index["M"]))

    def test_index_drops_episodes_without_verified_outcomes(self) -> None:
        from memory_fabric.estimators import build_exposure_index

        log = EventLog(":memory:")
        projection = Projection()

        def emit(event):
            for stored in log.append_many([event]):
                projection.apply(stored)

        emit(ev.episode_started(ts=1, agent_id="a", episode_id="ep1", task_id="t",
                                context={}, seed=None))
        emit(ev.exposure_decided(ts=1, agent_id="a", episode_id="ep1", memory_id="M",
                                 version=1, exposed=True, propensity=0.5, policy_id="p"))
        self.assertEqual(build_exposure_index(projection.state), {})
        log.close()

    def test_index_deduplicates_repeated_steps_in_one_episode(self) -> None:
        """One episode has one outcome, so a memory exposed at several steps is
        still a single observation."""
        from memory_fabric.estimators import build_exposure_index

        log = EventLog(":memory:")
        projection = Projection()

        def emit(event):
            for stored in log.append_many([event]):
                projection.apply(stored)

        emit(ev.episode_started(ts=1, agent_id="a", episode_id="ep1", task_id="t",
                                context={}, seed=None))
        for step in range(5):
            emit(ev.exposure_decided(ts=1, agent_id="a", episode_id="ep1", memory_id="M",
                                     version=1, exposed=True, propensity=0.5,
                                     policy_id="p", step=step))
        emit(ev.outcome_recorded(ts=1, episode_id="ep1", outcome=1.0, verifier_id="env"))

        self.assertEqual(len(build_exposure_index(projection.state)["M"]), 1)
        log.close()


class TestWilsonInterval(unittest.TestCase):
    def test_single_observation_is_not_treated_as_certainty(self) -> None:
        low, high = _wilson_interval(1.0, 1.0)
        self.assertLess(low, 0.9)
        self.assertGreater(high - low, 0.2)

    def test_interval_narrows_as_evidence_accumulates(self) -> None:
        narrow = _wilson_interval(0.7, 1000.0)
        wide = _wilson_interval(0.7, 5.0)
        self.assertLess(narrow[1] - narrow[0], wide[1] - wide[0])

    def test_interval_stays_within_bounds(self) -> None:
        for mean in (0.0, 0.5, 1.0):
            low, high = _wilson_interval(mean, 3.0)
            self.assertGreaterEqual(low, 0.0)
            self.assertLessEqual(high, 1.0)


if __name__ == "__main__":
    unittest.main()
