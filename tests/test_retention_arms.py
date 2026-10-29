"""The retention arms, and the invariant the whole H2 comparison rests on.

If the arms do not all hold the same number of live memories, "equal memory
budget" is not true and the primary metric compares stores of different sizes.
"""

from __future__ import annotations

import random
import unittest

from experiments.h2 import H2_WORLD, _play, _rngs
from experiments.retention_arms import ARMS, active_memories, make_oracle, prune
from experiments.ruleworld import RuleWorld, seed_memories
from amberlog import LifecycleState, Amberlog
from amberlog.exposure import EpsilonGreedyPolicy, TopKPolicy

BUDGET = 20


def warmed_store(seed: int = 0, episodes: int = 300):
    rngs = _rngs(seed)
    world = RuleWorld(H2_WORLD, rngs["world"])
    fabric = Amberlog(
        auto_activate=True,
        seed=seed,
        exposure_policy=EpsilonGreedyPolicy(epsilon=0.2, rank_by="relevance"),
    )
    seeded = seed_memories(fabric, world, rngs["world"])
    symptoms = [world.sample_symptom(rngs["tasks"]) for _ in range(episodes)]
    _play(fabric, world, symptoms, rngs["agent"], 3, "warm")
    fabric.policy = TopKPolicy("relevance")
    return fabric, world, seeded, rngs


class TestPrune(unittest.TestCase):
    def test_prunes_to_exactly_the_budget(self) -> None:
        for arm, scorer in ARMS.items():
            with self.subTest(arm=arm):
                fabric, _, _, rngs = warmed_store()
                try:
                    kept = prune(fabric, scorer, BUDGET, rngs["prune"])
                    self.assertEqual(len(kept), BUDGET)
                    self.assertEqual(len(active_memories(fabric)), BUDGET)
                finally:
                    fabric.close()

    def test_budget_holds_across_repeated_prunes(self) -> None:
        """Regression: ranking over every memory let already-deprecated ones
        occupy slots in the top `budget`. Their scores are stale — nothing has
        exposed them since — so they keep looking good, and the live store
        quietly falls below budget by a different amount in each arm.
        """
        for arm, scorer in ARMS.items():
            with self.subTest(arm=arm):
                fabric, world, _, rngs = warmed_store()
                try:
                    for _ in range(4):
                        prune(fabric, scorer, BUDGET, rngs["prune"])
                        self.assertEqual(len(active_memories(fabric)), BUDGET)
                        chunk = [world.sample_symptom(rngs["tasks"]) for _ in range(60)]
                        _play(fabric, world, chunk, rngs["agent"], 3, "eval")
                finally:
                    fabric.close()

    def test_pruned_memories_are_deprecated_not_destroyed(self) -> None:
        """A pruned store must still be able to explain itself."""
        fabric, _, _, rngs = warmed_store()
        try:
            before = len(fabric.state.memories)
            kept = prune(fabric, ARMS["naive"], BUDGET, rngs["prune"])
            self.assertEqual(len(fabric.state.memories), before)
            dropped = set(fabric.state.memories) - kept
            self.assertTrue(dropped)
            for memory_id in dropped:
                memory = fabric.get(memory_id)
                self.assertIs(memory.lifecycle_state, LifecycleState.DEPRECATED)
                self.assertTrue(memory.content)
                trail = [
                    e for e in fabric.audit_trail(memory_id)
                    if e.type == "LifecycleChanged"
                ]
                self.assertTrue(any("budget" in e.payload["reason"] for e in trail))
        finally:
            fabric.close()

    def test_pruned_memories_stop_being_retrievable(self) -> None:
        fabric, world, _, rngs = warmed_store()
        try:
            kept = prune(fabric, ARMS["naive"], BUDGET, rngs["prune"])
            for symptom in world.symptoms[:10]:
                result = fabric.retrieve("agent", symptom, k=5)
                self.assertTrue({m.id for m in result.exposed} <= kept)
        finally:
            fabric.close()

    def test_oracle_keeps_the_most_valuable_memories(self) -> None:
        fabric, _, seeded, rngs = warmed_store()
        try:
            truth = {s.memory_id: float(index) for index, s in enumerate(seeded)}
            kept = prune(fabric, make_oracle(truth), BUDGET, rngs["prune"])
            expected = {s.memory_id for s in seeded[-BUDGET:]}
            self.assertEqual(kept, expected)
        finally:
            fabric.close()

    def test_arms_disagree_about_what_to_keep(self) -> None:
        """If every arm kept the same set, the experiment would compare nothing."""
        kept_by_arm = {}
        for arm, scorer in ARMS.items():
            fabric, _, _, rngs = warmed_store()
            try:
                kept_by_arm[arm] = prune(fabric, scorer, BUDGET, rngs["prune"])
            finally:
                fabric.close()
        self.assertNotEqual(kept_by_arm["amortized"], kept_by_arm["naive"])
        self.assertNotEqual(kept_by_arm["amortized"], kept_by_arm["recency_importance"])
        self.assertNotEqual(kept_by_arm["frequency"], kept_by_arm["naive"])


if __name__ == "__main__":
    unittest.main()
