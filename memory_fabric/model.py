"""The memory object and its value types, per SPEC.md section 2.

A Memory is immutable per version. Changing content creates a new version.
Counters and value estimates live in MemoryStats, which is a projection of the
event log and is never written directly.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Any, Mapping

SCHEMA_VERSION = "0.3.0"


class MemoryType(str, Enum):
    EPISODIC = "episodic"
    SEMANTIC = "semantic"
    PROCEDURAL = "procedural"


class Scope(str, Enum):
    """Visibility. Independent of lifecycle state."""

    PRIVATE = "private"
    TEAM = "team"
    FEDERATED = "federated"

    @property
    def rank(self) -> int:
        return {"private": 0, "team": 1, "federated": 2}[self.value]


class WithdrawalBasis(str, Enum):
    """Why a memory was taken out of circulation.

    This exists because of a measurement. Phase A put the obvious rule — withdraw
    whatever was in context when an episode failed — on a real task and found it
    cut the rate at which a *correct* memory reached the prompt from 60% of
    episodes to 18%: actions are shared between situations, so the memory that
    asserted what the agent wrongly said was usually a correct memory about a
    different situation. Agreement with a mistake is not evidence of having
    caused it.

    So the basis is recorded rather than assumed, and `WEAK_BASES` names the ones
    that are known not to support a withdrawal on their own. The product does not
    refuse them — an operator may have reasons the store cannot see — but it
    stops presenting them as equivalent to evidence about the memory itself.
    """

    SENSITIVE_DATA = "sensitive_data"
    """A governance detector found a credential or personal data in it."""

    CONTRADICTED = "contradicted"
    """It conflicts with something the environment verified."""

    CONTRASTIVE_HARM = "contrastive_harm"
    """Its contrastive value estimate shows harm, interval below zero.

    Treated as a strong basis, but on thin evidence: PA' is the only measurement
    of it, and across 120 episodes it fired **three times** and all three
    withdrawals were of memories irrelevant to the episode that triggered them.
    That is too small a sample to move it into `WEAK_BASES` — three events cannot
    establish a rate — and too poor a showing to leave implying more than it has
    earned. What it currently supports is "rare", not "accurate".
    """

    RETRACTED_AT_ORIGIN = "retracted_at_origin"
    """An imported memory whose origin store withdrew it."""

    OPERATOR_JUDGEMENT = "operator_judgement"
    """A human decided, for reasons outside the store."""

    CO_OCCURRENCE = "co_occurrence"
    """It was present when something went wrong. Measured to be harmful as a
    withdrawal rule; see Phase A."""

    UNSTATED = "unstated"
    """No basis was given. Recorded as its own value rather than left empty, so
    that a store can tell "nobody said" from "nobody was asked"."""


WEAK_BASES = frozenset({WithdrawalBasis.CO_OCCURRENCE, WithdrawalBasis.UNSTATED})
"""Bases that do not, on their own, support withdrawing a memory."""


class LifecycleState(str, Enum):
    """Health of a memory. Independent of scope."""

    CANDIDATE = "candidate"
    ACTIVE = "active"
    CONTESTED = "contested"
    QUARANTINED = "quarantined"
    DEPRECATED = "deprecated"
    DELETED = "deleted"


class SecurityClass(str, Enum):
    PUBLIC = "public"
    INTERNAL = "internal"
    RESTRICTED = "restricted"


class ProvenanceMethod(str, Enum):
    OBSERVED = "observed"
    CONSOLIDATED = "consolidated"
    SPECIALIZED = "specialized"
    GENERALIZED = "generalized"
    IMPORTED = "imported"
    MANUAL = "manual"


class FirewallDecision(str, Enum):
    ALLOW = "allow"
    ALLOW_WITH_WARNING = "allow_with_warning"
    REQUIRE_VALIDATION = "require_validation"
    QUARANTINE = "quarantine"
    DENY = "deny"

    @property
    def permits_sharing(self) -> bool:
        return self in (FirewallDecision.ALLOW, FirewallDecision.ALLOW_WITH_WARNING)


# States from which a memory may be exposed to an agent by default.
EXPOSABLE_STATES = frozenset({LifecycleState.ACTIVE})
# Exposable only under an exploration policy, carrying their hypothesis siblings.
EXPLORATORY_STATES = frozenset({LifecycleState.CONTESTED})
# Never exposable, whatever the policy.
BLOCKED_STATES = frozenset(
    {LifecycleState.QUARANTINED, LifecycleState.DEPRECATED, LifecycleState.DELETED}
)


def context_key(context: Mapping[str, Any] | None) -> str:
    """Canonical, stable string for a context, used to key per-context estimates."""
    if not context:
        return "*"
    items = sorted((str(k), context[k]) for k in context)
    return json.dumps(items, separators=(",", ":"), sort_keys=True, default=str)


@dataclass(frozen=True)
class Provenance:
    created_by: str
    source_episodes: tuple[str, ...] = ()
    parents: tuple[tuple[str, int], ...] = ()
    method: ProvenanceMethod = ProvenanceMethod.OBSERVED

    def to_json(self) -> dict[str, Any]:
        return {
            "created_by": self.created_by,
            "source_episodes": list(self.source_episodes),
            "parents": [list(p) for p in self.parents],
            "method": self.method.value,
        }

    @staticmethod
    def from_json(data: Mapping[str, Any]) -> "Provenance":
        return Provenance(
            created_by=data["created_by"],
            source_episodes=tuple(data.get("source_episodes", ())),
            parents=tuple((p[0], int(p[1])) for p in data.get("parents", ())),
            method=ProvenanceMethod(data.get("method", "observed")),
        )


@dataclass(frozen=True)
class Memory:
    """One immutable version of a memory."""

    id: str
    version: int
    type: MemoryType
    content: str
    provenance: Provenance
    context: Mapping[str, Any] = field(default_factory=dict)
    structured: Mapping[str, Any] | None = None
    embedding_ref: str | None = None
    scope: Scope = Scope.PRIVATE
    lifecycle_state: LifecycleState = LifecycleState.CANDIDATE
    hypothesis_set: str | None = None
    security_class: SecurityClass = SecurityClass.INTERNAL
    capabilities: tuple[str, ...] = ()
    created_at: int = 0
    superseded_at: int | None = None
    schema_version: str = SCHEMA_VERSION

    @property
    def context_key(self) -> str:
        return context_key(self.context)

    def to_json(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "version": self.version,
            "type": self.type.value,
            "content": self.content,
            "provenance": self.provenance.to_json(),
            "context": dict(self.context),
            "structured": dict(self.structured) if self.structured is not None else None,
            "embedding_ref": self.embedding_ref,
            "scope": self.scope.value,
            "lifecycle_state": self.lifecycle_state.value,
            "hypothesis_set": self.hypothesis_set,
            "security_class": self.security_class.value,
            "capabilities": list(self.capabilities),
            "created_at": self.created_at,
            "superseded_at": self.superseded_at,
            "schema_version": self.schema_version,
        }

    @staticmethod
    def from_json(data: Mapping[str, Any]) -> "Memory":
        return Memory(
            id=data["id"],
            version=int(data["version"]),
            type=MemoryType(data["type"]),
            content=data["content"],
            provenance=Provenance.from_json(data["provenance"]),
            context=dict(data.get("context") or {}),
            structured=dict(data["structured"]) if data.get("structured") else None,
            embedding_ref=data.get("embedding_ref"),
            scope=Scope(data.get("scope", "private")),
            lifecycle_state=LifecycleState(data.get("lifecycle_state", "candidate")),
            hypothesis_set=data.get("hypothesis_set"),
            security_class=SecurityClass(data.get("security_class", "internal")),
            capabilities=tuple(data.get("capabilities", ())),
            created_at=int(data.get("created_at", 0)),
            superseded_at=data.get("superseded_at"),
            schema_version=data.get("schema_version", SCHEMA_VERSION),
        )

    def evolve(self, **changes: Any) -> "Memory":
        return replace(self, **changes)


@dataclass(frozen=True)
class ValueEstimate:
    """A posterior over V(m, c). Never a bare number: see AGENTS.md principle 5."""

    mean: float
    ci_low: float
    ci_high: float
    n_eff: float
    estimator: str
    updated_at: int = 0
    contrastive: bool = False
    """Whether `mean` is a *difference* between exposing and withholding.

    This flag decides what the number is allowed to justify. A contrastive
    estimate answers "did this memory help?". A non-contrastive one answers only
    "how did episodes go when this memory was around?", which is the question
    that confuses value with relevance. Treating the two as interchangeable
    would let any frequently retrieved memory look valuable, so the distinction
    is carried in the type rather than left to the caller to remember.
    """

    @property
    def shows_benefit(self) -> bool:
        """True when this estimate is evidence that the memory *helps*.

        Requires a contrastive estimator: a lower bound above zero means nothing
        for an absolute success rate, which is above zero for almost any memory.
        """
        return self.contrastive and self.ci_low > 0.0

    def to_json(self) -> dict[str, Any]:
        return {
            "mean": self.mean,
            "ci_low": self.ci_low,
            "ci_high": self.ci_high,
            "n_eff": self.n_eff,
            "estimator": self.estimator,
            "updated_at": self.updated_at,
            "contrastive": self.contrastive,
        }

    @staticmethod
    def from_json(data: Mapping[str, Any]) -> "ValueEstimate":
        return ValueEstimate(
            mean=float(data["mean"]),
            ci_low=float(data["ci_low"]),
            ci_high=float(data["ci_high"]),
            n_eff=float(data["n_eff"]),
            estimator=data.get("estimator", ""),
            updated_at=int(data.get("updated_at", 0)),
            contrastive=bool(data.get("contrastive", False)),
        )


UNKNOWN_VALUE = ValueEstimate(
    mean=0.0,
    ci_low=float("-inf"),
    ci_high=float("inf"),
    n_eff=0.0,
    estimator="none",
    contrastive=False,
)


@dataclass
class MemoryStats:
    """Projected counters. Rebuilt from the event log; never authored directly."""

    memory_id: str
    value_estimate: ValueEstimate = UNKNOWN_VALUE
    value_by_context: dict[str, ValueEstimate] = field(default_factory=dict)
    exposures: int = 0
    withholdings: int = 0
    citations: int = 0
    validations_passed: int = 0
    validations_failed: int = 0
    last_exposed_at: int | None = None

    def value_in(self, context: Mapping[str, Any] | None) -> ValueEstimate:
        """Per-context estimate if we have one, else the pooled estimate.

        Transferability is this function evaluated off the origin context; it is
        not a separate field (CRITICAL_REVIEW section 3).
        """
        return self.value_by_context.get(context_key(context), self.value_estimate)
