"""RuleWorld: a synthetic environment where every memory's true value is known.

Why synthetic at all: validating a *value estimator* needs the value it is
estimating. No real benchmark provides that, so the estimator would be judged by
whether its numbers look plausible — which is how a confounded estimator passes
review (EVALUATION.md §1).

The world is built so the experiment can fail. Retrieval ranks by relevance, and
a distractor memory attached to an easy symptom is therefore exposed mainly on
episodes that would have succeeded anyway. Its true value is exactly zero and its
observed success rate is high, so any estimator that cannot separate the two
will rank it near the top.

Ground truth is analytic. The agent's probability of answering correctly is a
closed form given the exposed memories, so treatment effects are computed, not
simulated, and carry no Monte Carlo noise of their own.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Iterable, Mapping, Sequence

from memory_fabric import MemoryFabric, MemoryType
from memory_fabric.model import Memory

CLAIM = "claim"
DISTRACTOR = "distractor"


@dataclass(frozen=True)
class Rule:
    symptom: str
    correct_action: str
    n_plausible: int
    """How many actions the agent would guess among. Low means an easy symptom:
    a guess succeeds 1/n_plausible of the time even with no memory at all."""

    @property
    def guess_rate(self) -> float:
        return 1.0 / self.n_plausible


@dataclass
class WorldConfig:
    n_symptoms: int = 40
    n_actions: int = 8
    plausible_choices: tuple[int, ...] = (2, 3, 4, 5, 6)
    n_correct_claims: int = 40
    n_wrong_claims: int = 20
    n_distractors: int = 40
    compliance: float = 0.8
    """Probability the agent follows the top matching claim rather than guessing.

    0.8 was a guess, and it sits underneath every result in H1-H4. Measured
    against live models it is **1.00** — 45/45 trials across qwen2.5:3b,
    llama3.2:3b and qwen2.5:7b (research/results/live-ollama-validation.md).

    Left at 0.8 so the published results stay reproducible. The direction is
    favourable: a higher compliance widens the gap between a correct and a wrong
    memory, which makes value estimation easier, so the simulated numbers are
    conservative rather than flattered."""

    # --- v2: what the P4 world could not test (see prereg h2 §2) ----------
    coverage: float = 1.0
    """Fraction of symptoms a correct claim is written for.

    At 1.0 (the P4 setting) a wrong claim is almost always outranked by a
    correct one and never followed, so injected harm is inert and a forgetting
    experiment measures nothing. Below 1.0 the uncovered symptoms let wrong
    claims reach the top of the ranking.
    """

    rare_fraction: float = 0.0
    rare_rate: float = 0.05
    """Rare symptoms appear at `rare_rate` times the usual probability. Their
    memories accumulate almost no evidence, which is exactly the population a
    credit-driven policy has reason to delete (CRITICAL_REVIEW §2.5)."""


@dataclass
class Drift:
    """A scheduled change to the rules.

    Memories written against the old rules become wrong without being edited,
    which is the obsolescence case: nothing about the memory changed, only the
    world it described.
    """

    at_episode: int
    fraction: float = 0.4
    applied: bool = False


class RuleWorld:
    def __init__(self, config: WorldConfig, rng: random.Random) -> None:
        self.config = config
        self.actions = [f"act{i}" for i in range(config.n_actions)]
        self.rules: dict[str, Rule] = {}
        for index in range(config.n_symptoms):
            symptom = f"sym{index}"
            self.rules[symptom] = Rule(
                symptom=symptom,
                correct_action=rng.choice(self.actions),
                n_plausible=rng.choice(config.plausible_choices),
            )
        self.symptoms = list(self.rules)

        n_rare = int(round(config.rare_fraction * len(self.symptoms)))
        self.rare: set[str] = set(rng.sample(self.symptoms, n_rare)) if n_rare else set()
        # Sampling weights, normalised lazily by random.choices.
        self._weights = [
            config.rare_rate if s in self.rare else 1.0 for s in self.symptoms
        ]

    def sample_symptom(self, rng: random.Random) -> str:
        if not self.rare:
            return rng.choice(self.symptoms)
        return rng.choices(self.symptoms, weights=self._weights, k=1)[0]

    def apply_drift(self, fraction: float, rng: random.Random) -> set[str]:
        """Flip the correct action for a fraction of rules. Returns which."""
        count = int(round(fraction * len(self.symptoms)))
        flipped = set(rng.sample(self.symptoms, count))
        for symptom in flipped:
            rule = self.rules[symptom]
            self.rules[symptom] = Rule(
                symptom=symptom,
                correct_action=self.wrong_action(symptom, rng),
                n_plausible=rule.n_plausible,
            )
        return flipped

    def wrong_action(self, symptom: str, rng: random.Random) -> str:
        correct = self.rules[symptom].correct_action
        return rng.choice([a for a in self.actions if a != correct])

    # --- the agent's policy, in closed form ------------------------------

    def p_correct(self, symptom: str, ranked: Sequence[Mapping[str, object]]) -> float:
        """Probability the agent answers correctly, given what it was shown.

        `ranked` is the exposed memories' `structured` payloads, in the order the
        agent sees them. Only the top *matching claim* has any effect: a
        distractor, or a claim about another symptom, changes nothing — which is
        what makes their true value exactly zero and the confound clean.
        """
        rule = self.rules[symptom]
        top = next(
            (
                m
                for m in ranked
                if m.get("kind") == CLAIM and m.get("symptom") == symptom
            ),
            None,
        )
        if top is None:
            return rule.guess_rate
        followed = 1.0 if top.get("action") == rule.correct_action else 0.0
        q = self.config.compliance
        return q * followed + (1.0 - q) * rule.guess_rate

    def act(
        self, symptom: str, ranked: Sequence[Mapping[str, object]], rng: random.Random
    ) -> str:
        """Sample an action. The observed outcome is a draw on `p_correct`."""
        rule = self.rules[symptom]
        top = next(
            (m for m in ranked if m.get("kind") == CLAIM and m.get("symptom") == symptom),
            None,
        )
        if top is not None and rng.random() < self.config.compliance:
            return str(top.get("action"))
        # Guess among the plausible set, which always contains the right answer.
        plausible = self._plausible_actions(symptom)
        return rng.choice(plausible)

    def _plausible_actions(self, symptom: str) -> list[str]:
        rule = self.rules[symptom]
        others = [a for a in self.actions if a != rule.correct_action]
        # Deterministic given the rule, so the plausible set is stable across runs.
        picked = others[: rule.n_plausible - 1]
        return [rule.correct_action] + picked


@dataclass
class SeededMemory:
    memory_id: str
    kind: str
    symptom: str
    action: str | None
    structured: dict


def seed_memories(
    fabric: MemoryFabric, world: RuleWorld, rng: random.Random
) -> list[SeededMemory]:
    """Populate the store with correct claims, wrong claims and distractors.

    Content is written so the default hashing embedder can find it: the symptom
    token is distinctive, so a query for one symptom retrieves memories about it
    and scores the rest at zero.
    """
    config = world.config
    seeded: list[SeededMemory] = []
    symptoms = list(world.symptoms)

    def add(kind: str, symptom: str, action: str | None) -> None:
        if kind == CLAIM:
            content = f"When {symptom} occurs the correct response is {action}."
        else:
            content = f"{symptom} has been reported by several sites this quarter."
        structured = {"kind": kind, "symptom": symptom, "action": action}
        memory_id = fabric.remember(
            agent_id="seeder",
            content=content,
            type=MemoryType.PROCEDURAL if kind == CLAIM else MemoryType.EPISODIC,
            structured=structured,
            context={"symptom": symptom, "importance": _importance(kind, rng)},
        )
        seeded.append(SeededMemory(memory_id, kind, symptom, action, structured))

    # Partial coverage: only some symptoms get a correct claim, so a wrong claim
    # about an uncovered symptom can reach the top of the ranking and be acted
    # on. Rare symptoms are covered at the same rate as any other, so the
    # rare-but-correct memories the guardrail is about actually exist.
    covered_count = min(
        config.n_correct_claims, int(round(config.coverage * len(symptoms)))
    )
    covered = rng.sample(symptoms, covered_count)
    for symptom in covered:
        add(CLAIM, symptom, world.rules[symptom].correct_action)

    uncovered = [s for s in symptoms if s not in set(covered)]
    for index in range(config.n_wrong_claims):
        # Bias wrong claims toward uncovered symptoms, where nothing outranks
        # them; otherwise injected harm stays inert as it did in P4.
        pool = uncovered if (uncovered and index % 2 == 0) else symptoms
        symptom = rng.choice(pool)
        add(CLAIM, symptom, world.wrong_action(symptom, rng))

    for _ in range(config.n_distractors):
        add(DISTRACTOR, rng.choice(symptoms), None)

    return seeded


def _importance(kind: str, rng: random.Random) -> float:
    """A Generative-Agents-style importance rating.

    Claims rate above distractors, because a rater can see that one asserts an
    action and the other does not. Correct and wrong claims rate the same,
    because telling them apart requires outcomes — which is the whole point. An
    importance score correlated with correctness would make the baseline a
    straw man by handing it information no rater could have.
    """
    base = 0.7 if kind == CLAIM else 0.4
    return round(min(max(base + rng.uniform(-0.15, 0.15), 0.0), 1.0), 3)


def query_for(symptom: str) -> str:
    """Just the symptom token.

    The embedder splits on non-alphanumerics, so a name like `symptom_3` would
    tokenise as `symptom` + `3` and match every other symptom through the shared
    word. Single-token names keep retrieval topical, which is what the
    experiment needs: a memory about another symptom should score zero and be
    cut by the relevance floor, not drift into the context.
    """
    return symptom


def structured_of(memories: Iterable[Memory]) -> list[dict]:
    return [dict(m.structured or {}) for m in memories]
