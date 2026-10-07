"""Running RuleWorld episodes and computing ground truth from the event log.

Ground truth is reconstructed from the log rather than from bookkeeping kept on
the side. That costs a little code and buys two things: the treatment effects
are computed from exactly what the fabric recorded, and if the log were not
sufficient to reconstruct them, this would fail rather than quietly disagree.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Mapping, Sequence

from memory_fabric import MemoryFabric
from memory_fabric.events import EventType
from memory_fabric.exposure import EpsilonGreedyPolicy, TopKPolicy

from .ruleworld import RuleWorld, SeededMemory, WorldConfig, query_for, seed_memories


@dataclass
class RunConfig:
    n_episodes: int = 2000
    seed: int = 0
    epsilon: float | None = 0.2
    """None means the deterministic relevance-ranked policy (no overlap)."""
    k: int = 3
    pool: int = 12
    world: WorldConfig = field(default_factory=WorldConfig)


@dataclass
class EpisodeRecord:
    episode_id: str
    symptom: str
    outcome: float
    ranked_candidates: list[str]
    exposed: set[str]


@dataclass
class RunResult:
    fabric: MemoryFabric
    world: RuleWorld
    seeded: list[SeededMemory]
    episodes: list[EpisodeRecord]
    config: RunConfig

    @property
    def mean_outcome(self) -> float:
        if not self.episodes:
            return 0.0
        return sum(e.outcome for e in self.episodes) / len(self.episodes)

    def close(self) -> None:
        self.fabric.close()


def run(config: RunConfig) -> RunResult:
    """Seed a world and run episodes through the real fabric retrieval path."""
    rng = random.Random(config.seed)
    world = RuleWorld(config.world, rng)

    policy = (
        TopKPolicy("relevance")
        if config.epsilon is None
        else EpsilonGreedyPolicy(epsilon=config.epsilon, rank_by="relevance")
    )
    fabric = MemoryFabric(
        auto_activate=True, seed=config.seed, exposure_policy=policy
    )
    seeded = seed_memories(fabric, world, rng)

    episodes: list[EpisodeRecord] = []
    for index in range(config.n_episodes):
        symptom = world.sample_symptom(rng)
        session = fabric.session(
            "agent", f"task-{index}", {"symptom": symptom}
        )
        result = session.recall(query_for(symptom), k=config.k, pool=config.pool)
        exposed = list(result.exposed)
        action = world.act(symptom, [dict(m.structured or {}) for m in exposed], rng)
        outcome = 1.0 if action == world.rules[symptom].correct_action else 0.0
        session.record_outcome(outcome, verifier_id="env")
        session.close()
        episodes.append(
            EpisodeRecord(
                episode_id=session.episode_id,
                symptom=symptom,
                outcome=outcome,
                ranked_candidates=[],
                exposed={m.id for m in exposed},
            )
        )

    _attach_candidate_order(fabric, episodes)
    return RunResult(fabric, world, seeded, episodes, config)


def _attach_candidate_order(fabric: MemoryFabric, episodes: list[EpisodeRecord]) -> None:
    """Recover each episode's ranked candidate list from the log."""
    by_episode = {e.episode_id: e for e in episodes}
    for event in fabric.log.read():
        if event.type != EventType.RETRIEVAL_PERFORMED:
            continue
        record = by_episode.get(event.episode_id or "")
        if record is None:
            continue
        # The index returns candidates already ranked; the log preserves that
        # order, which is the order the agent would see them in.
        record.ranked_candidates = [c["memory_id"] for c in event.payload["candidates"]]


def ground_truth(result: RunResult) -> dict[str, float]:
    """The exact average treatment effect of each memory.

    For every episode where a memory was a candidate, the effect of exposing it
    at its rank versus withholding it is computed in closed form. Averaging over
    those episodes gives the quantity an unbiased estimator is trying to
    recover — restricted to the population an estimator actually has data from.
    """
    world = result.world
    fabric = result.fabric
    structured = {
        memory_id: dict(memory.structured or {})
        for memory_id, memory in fabric.state.memories.items()
    }

    totals: dict[str, float] = {}
    counts: dict[str, int] = {}

    for episode in result.episodes:
        ranked = episode.ranked_candidates
        if not ranked:
            continue
        exposed_in_order = [m for m in ranked if m in episode.exposed]

        for candidate in ranked:
            with_it = (
                exposed_in_order
                if candidate in episode.exposed
                else _insert_at_rank(exposed_in_order, candidate, ranked)
            )
            without_it = [m for m in exposed_in_order if m != candidate]

            effect = world.p_correct(
                episode.symptom, [structured[m] for m in with_it]
            ) - world.p_correct(
                episode.symptom, [structured[m] for m in without_it]
            )
            totals[candidate] = totals.get(candidate, 0.0) + effect
            counts[candidate] = counts.get(candidate, 0) + 1

    return {mid: totals[mid] / counts[mid] for mid in totals if counts[mid]}


def _insert_at_rank(
    exposed_in_order: Sequence[str], candidate: str, ranked: Sequence[str]
) -> list[str]:
    """Place a withheld candidate back where its relevance rank puts it."""
    position = ranked.index(candidate)
    out = list(exposed_in_order)
    for index, memory_id in enumerate(out):
        if ranked.index(memory_id) > position:
            out.insert(index, candidate)
            return out
    out.append(candidate)
    return out


def estimable_memories(result: RunResult) -> set[str]:
    """The pre-registered analysis population: memories with at least one
    exposure decision in an episode carrying a verified outcome."""
    outcomes = {
        episode_id
        for episode_id, episode in result.fabric.state.episodes.items()
        if episode.has_outcome and episode.verifier_id
    }
    return {
        record.memory_id
        for record in result.fabric.state.exposures
        if record.episode_id in outcomes
    }


def exploration_overhead(base: RunConfig) -> dict[str, float]:
    """Paired runs: identical world and seed, randomised exposure or not."""
    greedy = run(RunConfig(**{**base.__dict__, "epsilon": None}))
    explore = run(base)
    try:
        greedy_mean = greedy.mean_outcome
        explore_mean = explore.mean_outcome
        overhead = (
            (greedy_mean - explore_mean) / greedy_mean if greedy_mean > 0 else 0.0
        )
        return {
            "greedy": greedy_mean,
            "explore": explore_mean,
            "overhead": overhead,
        }
    finally:
        greedy.close()
        explore.close()
