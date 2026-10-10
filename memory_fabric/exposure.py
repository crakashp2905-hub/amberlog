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

    @property
    def has_value_evidence(self) -> bool:
        """Whether this estimate **would survive being acted on**.

        Three conditions, and each one was needed:

        * an estimate exists at all — `value_mean` reports 0.0 for a memory with
          no estimate, which reads as "measured to have no effect" when the
          truth is "never measured";
        * it is **contrastive** — an absolute success rate over episodes where a
          memory appeared cannot show the memory helped, which is the
          value/relevance confusion this project exists to avoid;
        * its credible interval **clears zero** — a mean of +0.10 on a single
          observation with an interval of [-0.40, 0.60] is not evidence that a
          memory helps.

        This is the rule the firewall already applies to scope promotion
        (`ValueEstimate.shows_benefit`) and retention applies to withdrawal, so
        it makes one standard out of three rather than inventing a fourth.

        The earlier version checked only `n_eff > 0`, which was too weak to be
        useful: a candidate with one observation outranked an unevaluated
        candidate nineteen times more relevant. Recorded at the time in
        research/decisions/2026-10-10-value-ranking-ignores-uncertainty.md and
        deliberately left unfixed until the registered runs that depended on
        the old behaviour had finished.
        """
        if self.value is None or self.value.n_eff <= 0.0:
            return False
        return self.value.shows_benefit or self.value.ci_high < 0.0


def _rank_key(candidate: Candidate, rank_by: str) -> tuple[float, float, str]:
    """Order candidates best-first, with **relevance as the tie-break**.

    This was a bug worth the comment. Ranking by value used
    `(-value_mean, memory_id)`, and `value_mean` is 0.0 for a memory nothing is
    known about — so in a store with no value evidence every candidate tied at
    zero and the decision fell through to the memory id. Ids are ULIDs, which
    are time-ordered, so "rank by value" silently became "rank by creation
    time": the oldest memories were exposed every time and relevance was
    discarded entirely.

    The consequence was worse than an odd ordering. A newly written or newly
    imported memory has no value evidence, so it could never be exposed; and
    value evidence can only be earned by being exposed. Only the epsilon
    exploration broke the deadlock, weakly. In a four-agent federation with 36
    imports competing for three slots, not one import was retrieved in eight
    consecutive episodes.

    So an unevaluated candidate is ordered by the only signal that exists for
    it, which is relevance, and the id remains only to keep the sort
    deterministic.
    """
    if rank_by == "relevance":
        return (-candidate.relevance, -candidate.relevance, candidate.memory_id)

    # Rank on value only where the estimate would survive being acted on.
    # Otherwise fall back to relevance, which is the only signal that exists
    # for an unevaluated memory. AGENTS.md principle 5 — credit is a
    # distribution, not a number — and the exposure policy was the one of seven
    # call sites that read the mean and discarded the rest.
    if candidate.has_value_evidence:
        return (-candidate.value_mean, -candidate.relevance, candidate.memory_id)
    return (0.0, -candidate.relevance, candidate.memory_id)


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

    def _key(self, candidate: Candidate) -> tuple[float, float, str]:
        return _rank_key(candidate, self.rank_by)

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
        ordered = sorted(candidates, key=lambda c: _rank_key(c, self.rank_by))
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
