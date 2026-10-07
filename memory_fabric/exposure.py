"""Exposure policies: deciding which retrieved candidates reach the agent.

Every decision reports the probability with which it was taken. That single
float is what makes unbiased value estimation possible later, and it cannot be
reconstructed after the fact (CRITICAL_REVIEW section 2.2): memories are
retrieved *because* they look relevant, and relevant-looking situations are the
easy ones, so observational credit is biased upward and the bias compounds.

A policy that is deterministic in some region must say so, via
`declares_overlap`. Estimators treat those regions as having no overlap and
refuse to draw causal conclusions from them.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Protocol, Sequence

from .model import ValueEstimate


@dataclass(frozen=True)
class Candidate:
    """A retrieval hit, before the exposure decision."""

    memory_id: str
    version: int
    relevance: float
    value: ValueEstimate | None = None

    @property
    def value_mean(self) -> float:
        return self.value.mean if self.value is not None else 0.0


@dataclass(frozen=True)
class ExposureDecision:
    candidate: Candidate
    exposed: bool
    propensity: float  # P(this decision), so P(withhold) for a withheld memory

    def __post_init__(self) -> None:
        if not 0.0 < self.propensity <= 1.0:
            raise ValueError(f"propensity must be in (0, 1], got {self.propensity}")


class ExposurePolicy(Protocol):
    id: str
    declares_overlap: bool
    needs_value: bool
    """Whether this policy consults `Candidate.value`.

    Estimating a value for every candidate on every retrieval is not free, and a
    relevance-ranked policy never looks at the result. Declaring it lets the
    retrieval path skip the work rather than compute it and throw it away.
    """

    def decide(
        self, candidates: Sequence[Candidate], k: int, rng: random.Random
    ) -> list[ExposureDecision]: ...


class TopKPolicy:
    """Deterministic: expose the k best candidates.

    `declares_overlap = False` is the important part. This policy is a
    reasonable production default, but data it produces cannot support causal
    estimation, and it says so rather than letting an estimator assume
    otherwise.
    """

    id = "top_k"
    declares_overlap = False
    needs_value = False

    def __init__(self, rank_by: str = "relevance") -> None:
        if rank_by not in ("relevance", "value"):
            raise ValueError("rank_by must be 'relevance' or 'value'")
        self.rank_by = rank_by
        self.id = f"top_k:{rank_by}"
        self.needs_value = rank_by == "value"

    def _key(self, candidate: Candidate) -> tuple[float, str]:
        score = candidate.relevance if self.rank_by == "relevance" else candidate.value_mean
        return (-score, candidate.memory_id)

    def decide(
        self, candidates: Sequence[Candidate], k: int, rng: random.Random
    ) -> list[ExposureDecision]:
        ordered = sorted(candidates, key=self._key)
        chosen = {c.memory_id for c in ordered[:k]}
        return [
            ExposureDecision(candidate=c, exposed=c.memory_id in chosen, propensity=1.0)
            for c in candidates
        ]


class EpsilonGreedyPolicy:
    """Expose the top k, but randomise each decision with probability epsilon.

    Randomisation is what creates overlap: sometimes a memory that would have
    been shown is withheld, and sometimes one that would not have been shown is
    exposed. Both directions are needed, and both carry a known propensity.

    The cost is real, and the exploration overhead it causes must be reported as
    a cost in any result (EVALUATION.md section 2).
    """

    id = "epsilon_greedy"
    declares_overlap = True
    needs_value = True

    def __init__(self, epsilon: float = 0.1, rank_by: str = "value") -> None:
        if not 0.0 < epsilon < 1.0:
            raise ValueError("epsilon must be in (0, 1) for the policy to have overlap")
        if rank_by not in ("relevance", "value"):
            raise ValueError("rank_by must be 'relevance' or 'value'")
        self.epsilon = epsilon
        self.rank_by = rank_by
        self.id = f"epsilon_greedy:{rank_by}:{epsilon}"
        self.needs_value = rank_by == "value"

    def decide(
        self, candidates: Sequence[Candidate], k: int, rng: random.Random
    ) -> list[ExposureDecision]:
        def key(candidate: Candidate) -> tuple[float, str]:
            score = candidate.relevance if self.rank_by == "relevance" else candidate.value_mean
            return (-score, candidate.memory_id)

        ordered = sorted(candidates, key=key)
        greedy = {c.memory_id for c in ordered[:k]}
        eps = self.epsilon
        decisions: list[ExposureDecision] = []
        for candidate in candidates:
            would_expose = candidate.memory_id in greedy
            # With probability eps the decision is made by a coin flip instead
            # of by the ranking, so P(expose) is a mixture of the two.
            p_expose = (1.0 - eps) * (1.0 if would_expose else 0.0) + eps * 0.5
            exposed = rng.random() < p_expose
            propensity = p_expose if exposed else 1.0 - p_expose
            decisions.append(
                ExposureDecision(candidate=candidate, exposed=exposed, propensity=propensity)
            )
        return decisions


class AlwaysExposePolicy:
    """Expose every candidate. Used by baselines and by tests."""

    id = "always"
    declares_overlap = False
    needs_value = False

    def decide(
        self, candidates: Sequence[Candidate], k: int, rng: random.Random
    ) -> list[ExposureDecision]:
        return [
            ExposureDecision(candidate=c, exposed=True, propensity=1.0) for c in candidates
        ]


POLICIES: dict[str, type] = {
    "top_k": TopKPolicy,
    "epsilon_greedy": EpsilonGreedyPolicy,
    "always": AlwaysExposePolicy,
}


def build_policy(spec: str | ExposurePolicy) -> ExposurePolicy:
    if not isinstance(spec, str):
        return spec
    if spec not in POLICIES:
        raise KeyError(f"unknown exposure policy {spec!r}; known: {sorted(POLICIES)}")
    return POLICIES[spec]()
