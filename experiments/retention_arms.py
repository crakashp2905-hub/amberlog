"""The competing answers to "what should we forget?".

Each arm scores every memory; the top `budget` survive. They differ only in the
ranking, so the comparison isolates the forgetting decision rather than
confounding it with a change to retrieval.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from typing import Callable, Mapping

from amberlog import LifecycleState, Amberlog
from amberlog.estimators import build_estimator

Scorer = Callable[[Amberlog, random.Random], dict[str, float]]

# Generative-Agents-style exponential recency decay, per episode of age.
RECENCY_DECAY = 0.995


def score_random(fabric: Amberlog, rng: random.Random) -> dict[str, float]:
    return {memory_id: rng.random() for memory_id in fabric.state.memories}


def score_frequency(fabric: Amberlog, rng: random.Random) -> dict[str, float]:
    """What a relevance-only system effectively keeps: whatever gets retrieved.

    Retrieval frequency is the global shadow of relevance ranking — a memory
    that keeps coming back is the one such a system would never drop.
    """
    return {
        memory_id: float(fabric.state.stats_for(memory_id).exposures)
        for memory_id in fabric.state.memories
    }


def score_recency_importance(fabric: Amberlog, rng: random.Random) -> dict[str, float]:
    """Recency decay plus a stated importance rating, as in Generative Agents.

    Both components are normalised to [0,1] and summed, which is the shape of
    the original score minus the query-dependent relevance term (meaningless
    for a global retention decision).
    """
    state = fabric.state
    now = max(
        (s.last_exposed_at or 0 for s in state.stats.values()),
        default=0,
    )
    scores: dict[str, float] = {}
    for memory_id, memory in state.memories.items():
        stats = state.stats_for(memory_id)
        last = stats.last_exposed_at or memory.created_at
        age_ms = max(now - last, 0)
        # Age in "episodes" is not available here; milliseconds is monotonic in
        # it, which is all a decay needs.
        recency = RECENCY_DECAY ** (age_ms / 1000.0)
        importance = float(memory.context.get("importance", 0.5))
        scores[memory_id] = recency + importance
    return scores


def _estimator_scorer(estimator_id: str) -> Scorer:
    def scorer(fabric: Amberlog, rng: random.Random) -> dict[str, float]:
        estimator = build_estimator(estimator_id)
        estimator.fit(fabric.state)
        scores: dict[str, float] = {}
        for memory_id in fabric.state.memories:
            value = estimator.estimate(memory_id)
            mean = value.mean
            # An estimator that declines is treated as "no reason to keep this",
            # which is the decision a retention policy would actually face.
            scores[memory_id] = mean if math.isfinite(mean) else -math.inf
        return scores

    return scorer


score_naive = _estimator_scorer("naive_usage")
score_amortized = _estimator_scorer("amortized")


def make_oracle(truth: Mapping[str, float]) -> Scorer:
    """Upper bound: rank by the true value. Not a competitor."""

    def scorer(fabric: Amberlog, rng: random.Random) -> dict[str, float]:
        return {
            memory_id: truth.get(memory_id, -math.inf)
            for memory_id in fabric.state.memories
        }

    return scorer


ARMS: dict[str, Scorer] = {
    "random": score_random,
    "frequency": score_frequency,
    "recency_importance": score_recency_importance,
    "naive": score_naive,
    "amortized": score_amortized,
}

BASELINES = ("frequency", "recency_importance", "naive")
CHALLENGER = "amortized"


def active_memories(fabric: Amberlog) -> list[str]:
    return [
        memory_id
        for memory_id, memory in fabric.state.memories.items()
        if memory.lifecycle_state is LifecycleState.ACTIVE
    ]


def prune(fabric: Amberlog, scorer: Scorer, budget: int, rng: random.Random) -> set[str]:
    """Keep the top `budget` **active** memories; deprecate the rest.

    Ranking over every memory in the store would let already-deprecated ones
    occupy slots in the top `budget` — they are still in `state.memories`, and a
    stale score keeps them looking good because nothing has exposed them since.
    The store would then quietly fall below budget, by a different amount in
    each arm, and the "equal memory budget" the comparison rests on would not
    hold.

    Uses the fabric's own `forget`, so each removal is an event with a reason
    and the store can still explain what happened: a pruned memory is
    deprecated, not destroyed.
    """
    scores = scorer(fabric, rng)
    ranked = sorted(
        active_memories(fabric),
        key=lambda m: (-scores.get(m, -math.inf), m),
    )
    keep = set(ranked[:budget])
    for memory_id in ranked[budget:]:
        fabric.forget(memory_id, reason="pruned to budget", actor="retention-experiment")
    return keep
