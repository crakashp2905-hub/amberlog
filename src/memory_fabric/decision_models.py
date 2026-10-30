"""Typed, calibrated decision proposals that cannot grant authority.

Decision models rank options and may abstain.  Their output is deliberately a
*proposal*: callers must still pass the selected action through ``ActionGate``.
No probability, model family, or confidence threshold can bypass that gate.
"""

from __future__ import annotations

__stability__ = "experimental"

import math
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Protocol, Sequence


class DecisionModelError(ValueError):
    """A decision model returned a malformed or unsafe proposal."""


@dataclass(frozen=True)
class DecisionOption:
    id: str
    description: str
    action: str | None = None
    parameters: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class DecisionContext:
    query: str
    options: tuple[DecisionOption, ...]
    evidence_ids: tuple[str, ...] = ()
    constraints: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.options:
            raise DecisionModelError("at least one option is required")
        ids = [option.id for option in self.options]
        if len(ids) != len(set(ids)):
            raise DecisionModelError("option ids must be unique")


@dataclass(frozen=True)
class DecisionProposal:
    selected: str | None
    probabilities: Mapping[str, float]
    abstained: bool
    confidence: float
    evidence_ids: tuple[str, ...] = ()
    reasons: tuple[str, ...] = ()
    model_id: str = "unknown"
    requires_system2: bool = False

    def validate(self, context: DecisionContext) -> "DecisionProposal":
        expected = {option.id for option in context.options}
        if set(self.probabilities) != expected:
            raise DecisionModelError("probabilities must cover every option exactly once")
        values = tuple(self.probabilities.values())
        if any(not math.isfinite(value) or value < 0.0 or value > 1.0 for value in values):
            raise DecisionModelError("probabilities must be finite values in [0, 1]")
        if not math.isclose(sum(values), 1.0, abs_tol=1e-6):
            raise DecisionModelError("probabilities must sum to 1")
        if self.abstained != (self.selected is None):
            raise DecisionModelError("abstention and selected option disagree")
        if self.selected is not None and self.selected not in expected:
            raise DecisionModelError("selected option is not in the decision context")
        if not 0.0 <= self.confidence <= 1.0:
            raise DecisionModelError("confidence must be in [0, 1]")
        return self


class DecisionModel(Protocol):
    model_id: str

    def decide(self, context: DecisionContext) -> DecisionProposal: ...


@dataclass(frozen=True)
class EscalationPolicy:
    """Risk-sensitive System 1 to System 2 routing policy."""

    min_confidence: float = 0.8
    max_entropy: float = 0.5
    consequential_actions: frozenset[str] = frozenset()

    def requires_system2(self, proposal: DecisionProposal,
                         context: DecisionContext) -> bool:
        proposal.validate(context)
        entropy = -sum(p * math.log(p) for p in proposal.probabilities.values() if p)
        max_entropy = math.log(len(proposal.probabilities))
        normalized = entropy / max_entropy if max_entropy else 0.0
        selected = next((o for o in context.options if o.id == proposal.selected), None)
        consequential = selected is not None and selected.action in self.consequential_actions
        return (proposal.abstained or proposal.confidence < self.min_confidence
                or normalized > self.max_entropy or consequential)


class DeterministicDecisionModel:
    """Dependency-free baseline: score supplied features, tie -> abstain."""

    model_id = "deterministic-v1"

    def __init__(self, scores: Mapping[str, float]) -> None:
        self.scores = dict(scores)

    def decide(self, context: DecisionContext) -> DecisionProposal:
        raw = {option.id: max(0.0, float(self.scores.get(option.id, 0.0)))
               for option in context.options}
        total = sum(raw.values())
        probabilities = ({key: value / total for key, value in raw.items()} if total
                         else {key: 1.0 / len(raw) for key in raw})
        ordered = sorted(probabilities.items(), key=lambda item: (-item[1], item[0]))
        tied = len(ordered) > 1 and math.isclose(ordered[0][1], ordered[1][1])
        selected = None if tied else ordered[0][0]
        return DecisionProposal(
            selected=selected,
            probabilities=probabilities,
            abstained=selected is None,
            confidence=ordered[0][1],
            evidence_ids=context.evidence_ids,
            reasons=("top-score tie" if tied else "highest deterministic score",),
            model_id=self.model_id,
        ).validate(context)


class CallableDecisionModel:
    """Adapter for Laya, Jev, encoder classifiers, or another local model.

    The callable returns option probabilities. Validation remains inside the
    fabric boundary, independent of the third-party model implementation.
    """

    def __init__(self, model_id: str,
                 predict: Callable[[DecisionContext], Mapping[str, float]]) -> None:
        self.model_id = model_id
        self.predict = predict

    def decide(self, context: DecisionContext) -> DecisionProposal:
        probabilities = dict(self.predict(context))
        if not probabilities:
            raise DecisionModelError("model returned no probabilities")
        ordered = sorted(probabilities.items(), key=lambda item: (-item[1], item[0]))
        proposal = DecisionProposal(
            selected=ordered[0][0],
            probabilities=probabilities,
            abstained=False,
            confidence=ordered[0][1],
            evidence_ids=context.evidence_ids,
            reasons=("highest model probability",),
            model_id=self.model_id,
        )
        return proposal.validate(context)


def route_decision(model: DecisionModel, context: DecisionContext,
                   policy: EscalationPolicy) -> DecisionProposal:
    """Validate a model proposal and annotate whether System 2 is required."""

    proposal = model.decide(context).validate(context)
    return DecisionProposal(
        selected=proposal.selected,
        probabilities=dict(proposal.probabilities),
        abstained=proposal.abstained,
        confidence=proposal.confidence,
        evidence_ids=proposal.evidence_ids,
        reasons=proposal.reasons,
        model_id=proposal.model_id,
        requires_system2=policy.requires_system2(proposal, context),
    )


def brier_score(proposals: Sequence[DecisionProposal], outcomes: Sequence[str],
                option_ids: Sequence[str]) -> float:
    """Multiclass Brier score for calibration reports (lower is better)."""

    if not proposals or len(proposals) != len(outcomes):
        raise DecisionModelError("proposals and outcomes must have equal non-zero length")
    return sum(
        sum((proposal.probabilities.get(option, 0.0) - float(option == outcome)) ** 2
            for option in option_ids)
        for proposal, outcome in zip(proposals, outcomes, strict=True)
    ) / len(proposals)
