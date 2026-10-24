"""The memory object and its value types, per SPEC.md section 2.

A Memory is immutable per version. Changing content creates a new version.
Counters and value estimates live in MemoryStats, which is a projection of the
event log and is never written directly.
"""

from __future__ import annotations

__stability__ = "stable"

import json
from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Any, Mapping

# `identity` imports only `ids`, so this direction carries no cycle.
from .identity import DEFAULT_TENANT

SCHEMA_VERSION = "0.13.0"


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


PERMISSIONS = ("read", "write", "approve", "retract")
"""What an agent can be granted on a collection. `read` is attachment: the
collection's members become readable even when private. `write` lets it add
its own memories. `approve` and `retract` let an authenticated agent validate
and withdraw the collection's members without the operator role."""


def visible_to(memory: "Memory", agent_id: str | None, state: Any = None) -> bool:
    """Whether scope lets `agent_id` read `memory` inside its own store.

    `private` is the agent that wrote it; `team` and `federated` are every
    agent in the memory's tenant (tenancy is checked separately, first).
    `agent_id` None is a caller that is not agent-scoped -- an operator, or
    the store's own maintenance -- and scope does not restrict it, the same
    convention `tenant_id` None follows in the enforcer.

    Retrieval ignored scope until 2026-10-18: a validated private memory, a
    restricted one included, was returned to every agent in the tenant,
    although the specification and glossary define scope as visibility
    (docs/SECURITY_REVIEW.md F10).
    """
    if agent_id is None or memory.scope is not Scope.PRIVATE:
        return True
    if memory.provenance.created_by == agent_id:
        return True
    # Attached through a collection: `read` on a collection that holds it.
    return state is not None and granted(state, memory.tenant_id, agent_id, memory.id, "read")


def granted(state: Any, tenant_id: str, agent_id: str, memory_id: str, permission: str) -> bool:
    """Whether `agent_id` holds `permission` on a collection containing `memory_id`."""
    for (tenant, _), collection in getattr(state, "collections", {}).items():
        if tenant == tenant_id and memory_id in collection.members \
                and permission in collection.grants.get(agent_id, ()):
            return True
    return False


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
# States that record a decision to take a memory out of circulation.
#
# Distinct from BLOCKED_STATES, which happens to hold the same members today
# and answers a different question: BLOCKED is "may this be exposed", this is
# "was this withdrawn". Re-ingesting a withdrawn document must not restore it,
# and that test is about the decision rather than about exposability -- a
# future non-exposable state that is not a withdrawal would belong in one and
# not the other.
WITHDRAWN_STATES = frozenset(
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
    tenant_id: str = DEFAULT_TENANT
    """Whose data this is. An authorisation boundary, not a physical one:
    `_eligible_ids` and `Enforcer.check` refuse to cross it, so no ranking
    policy, index query or federation import can surface one tenant's knowledge
    to another. It does not isolate against a caller holding the file — see
    `identity.py` and DEPLOYMENT.md. Independent of `scope`, which says how far
    a memory may travel *within* a tenant."""
    lifecycle_state: LifecycleState = LifecycleState.CANDIDATE
    hypothesis_set: str | None = None
    security_class: SecurityClass = SecurityClass.INTERNAL
    capabilities: tuple[str, ...] = ()
    created_at: int = 0
    """**Recorded** time: when this store learned the claim.

    Distinct from `valid_from`/`valid_to`, which say when the claim is true of
    the world. One timestamp cannot answer both "what was true then?" and
    "what did we know then?", and `relevance_v1`'s `temporal_drift` family is
    where conflating them costs: a retriever with only a recorded time cannot
    tell a fact that *was* true from one that is.
    """
    valid_from: int | None = None
    """When the claim starts applying to the world. None means "as far back as
    anyone knows", which is the honest reading for a memory written before
    this field existed — not "never valid"."""
    valid_to: int | None = None
    """When it stops. None means open-ended, i.e. still current."""
    superseded_at: int | None = None
    schema_version: str = SCHEMA_VERSION

    @property
    def context_key(self) -> str:
        return context_key(self.context)

    def applies_at(self, when: int | None) -> bool:
        """Whether this claim is true of the world at `when`.

        `when` None means "do not filter", which is the right default for a
        task that does not say what time it is about. A memory with no validity
        window applies always — see `valid_from`.

        Half-open: `valid_from <= when < valid_to`. A closed upper bound would
        make two consecutive claims both apply at the instant one replaces the
        other, and "both answers are current" is the one thing a temporal
        filter must not say.
        """
        if when is None:
            return True
        if self.valid_from is not None and when < self.valid_from:
            return False
        if self.valid_to is not None and when >= self.valid_to:
            return False
        return True

    @property
    def is_open_ended(self) -> bool:
        """No end to its validity, i.e. still current as far as this store knows."""
        return self.valid_to is None

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
            "tenant_id": self.tenant_id,
            "lifecycle_state": self.lifecycle_state.value,
            "hypothesis_set": self.hypothesis_set,
            "security_class": self.security_class.value,
            "capabilities": list(self.capabilities),
            "created_at": self.created_at,
            "valid_from": self.valid_from,
            "valid_to": self.valid_to,
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
            # A store written before tenancy existed replays into the default
            # tenant, so an existing single-tenant deployment needs no
            # migration and behaves identically.
            tenant_id=data.get("tenant_id") or DEFAULT_TENANT,
            lifecycle_state=LifecycleState(data.get("lifecycle_state", "candidate")),
            hypothesis_set=data.get("hypothesis_set"),
            security_class=SecurityClass(data.get("security_class", "internal")),
            capabilities=tuple(data.get("capabilities", ())),
            created_at=int(data.get("created_at", 0)),
            # Absent in a log written before 0.7.0, and absent means
            # open-ended rather than invalid: an older store's memories stay
            # applicable at every time, which is exactly how they behaved.
            valid_from=data.get("valid_from"),
            valid_to=data.get("valid_to"),
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
