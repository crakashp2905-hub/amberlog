"""Two contexts that agree on an `o` fraction of the rules.

Overlap is the axis the whole federation question turns on. With `o=1` the two
agents inhabit the same world and sharing everything is free; with `o=0` a
memory from one is actively wrong in the other. Only in between is there
anything to be selective about.

The symptom set is shared, so a memory retrieved in either context looks equally
relevant. What differs is whether its claim is *right here* — which is exactly
the thing relevance cannot see.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

from .ruleworld import Rule, RuleWorld, WorldConfig


@dataclass
class ContextPair:
    a: RuleWorld
    b: RuleWorld
    overlap: float
    shared: frozenset[str]
    """Symptoms where both contexts agree on the correct action."""

    def worlds(self) -> tuple[RuleWorld, RuleWorld]:
        return (self.a, self.b)


def build_contexts(
    config: WorldConfig, overlap: float, rng: random.Random
) -> ContextPair:
    """Build two worlds agreeing on `overlap` of their rules.

    Context B starts as a copy of A, then the non-shared fraction has its
    correct actions reassigned. `n_plausible` is held identical across contexts
    so task difficulty does not vary with overlap — otherwise a change in
    success could be difficulty moving rather than transfer working.
    """
    if not 0.0 <= overlap <= 1.0:
        raise ValueError("overlap must be in [0, 1]")

    world_a = RuleWorld(config, rng)
    world_b = RuleWorld(config, random.Random(rng.random()))

    symptoms = list(world_a.symptoms)
    shared_count = int(round(overlap * len(symptoms)))
    shared = set(rng.sample(symptoms, shared_count))

    world_b.rules = {}
    for symptom in symptoms:
        rule_a = world_a.rules[symptom]
        if symptom in shared:
            action = rule_a.correct_action
        else:
            action = world_a.wrong_action(symptom, rng)
        world_b.rules[symptom] = Rule(
            symptom=symptom,
            correct_action=action,
            n_plausible=rule_a.n_plausible,
        )
    world_b.symptoms = symptoms
    world_b.rare = set()
    world_b._weights = [1.0] * len(symptoms)

    return ContextPair(a=world_a, b=world_b, overlap=overlap, shared=frozenset(shared))


def true_value_in(world: RuleWorld, structured: dict) -> float:
    """Sign of a claim's worth in a given context, used for negative transfer.

    Positive when the claim names that context's correct action, negative when
    it names another, zero when it asserts no action at all.
    """
    if structured.get("kind") != "claim":
        return 0.0
    symptom = structured.get("symptom")
    if symptom not in world.rules:
        return 0.0
    correct = world.rules[symptom].correct_action
    return 1.0 if structured.get("action") == correct else -1.0
