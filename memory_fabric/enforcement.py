"""Phase 3 — one enforcement layer, and action-time re-verification.

The point of the roadmap's Phase 3 is that integrity state has to change what an
agent *does*, not merely what a dashboard shows. Two gaps made that untrue:

**There was no enforcement boundary.** `retrieve()` filtered on lifecycle state,
but `fabric.get()` returned any memory regardless, so an adapter could reach
past the check without knowing it had. `get()` is now documented as inspection
only and `use()` is the enforced read; `Enforcer.check` is the single layer both
the retrieval path and any adapter must go through.

**There was a time-of-check/time-of-use gap by construction.** Exposure was
checked at retrieval and never again, so a memory retracted between retrieval
and a consequential action was still acted on. An `ExposureToken` now binds the
decision to an exact memory version *and* to the log revision it was made at, so
`verify_at_action` can tell that the world moved.

A decision never carries memory content. Auditing a denial by logging what was
denied would move the content into exactly the secondary surfaces the governance
layer exists to keep it out of — the reviewer is told the *kind* of problem,
which is what the decision needs (roadmap §3, "audit denials without leaking
restricted memory content").
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from .model import (
    BLOCKED_STATES,
    EXPLORATORY_STATES,
    EXPOSABLE_STATES,
    LifecycleState,
    WEAK_BASES,
)


class RiskLevel(str, Enum):
    """How much the caller is about to stake on the memory.

    The same integrity state warrants different behaviour depending on what is
    being done with it, which is the roadmap's §3 requirement: low risk may be
    flagged, medium may require revalidation, high must be blocked.
    """

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class Verdict(str, Enum):
    USABLE = "usable"
    WARN = "warn"
    """Usable, with something the caller should surface — a contested memory in
    a low-risk context, say."""

    REVALIDATE = "revalidate"
    """Not usable until something re-checks it. Distinct from DENY because the
    answer may become yes; conflating them loses that."""

    DENY = "deny"

    UNKNOWN = "unknown"
    """Integrity state could not be established. Deliberately **not** a synonym
    for usable: an unavailable check is a refusal for anything consequential,
    and invariant 9 requires the state be explicit rather than assumed."""


@dataclass(frozen=True)
class AccessDecision:
    """Why a memory may or may not be used. **Never carries content.**"""

    memory_id: str
    version: int
    verdict: Verdict
    reason_code: str
    detail: str = ""
    lifecycle_state: str = ""
    risk: RiskLevel = RiskLevel.LOW
    integrity_revision: int = 0

    @property
    def usable(self) -> bool:
        return self.verdict in (Verdict.USABLE, Verdict.WARN)

    def to_json(self) -> dict[str, Any]:
        return {
            "memory_id": self.memory_id,
            "version": self.version,
            "verdict": self.verdict.value,
            "reason_code": self.reason_code,
            "detail": self.detail,
            "lifecycle_state": self.lifecycle_state,
            "risk": self.risk.value,
            "integrity_revision": self.integrity_revision,
        }


@dataclass(frozen=True)
class ExposureToken:
    """A decision, bound tightly enough to be re-checked later.

    `integrity_revision` is the event log's head sequence when the decision was
    made. Anything that changes a memory's lifecycle appends an event, so a
    later head means the world may have moved and the token has to be
    re-verified rather than trusted.
    """

    memory_id: str
    version: int
    agent_id: str
    store_id: str
    verdict: Verdict
    integrity_revision: int
    issued_at_ms: int
    origin_store_id: str | None = None
    expires_at_ms: int | None = None
    policy_id: str = ""
    tenant_id: str | None = None
    """The tenant the decision was made for, so the re-check at action time is
    scoped the same way the retrieval was. Without it a token issued inside a
    tenant would be re-verified unscoped, and the time-of-use check would be
    weaker than the time-of-check one — which is the gap this class exists to
    close."""

    def expired(self, now_ms: int) -> bool:
        return self.expires_at_ms is not None and now_ms >= self.expires_at_ms

    def to_json(self) -> dict[str, Any]:
        return {
            "memory_id": self.memory_id,
            "version": self.version,
            "agent_id": self.agent_id,
            "store_id": self.store_id,
            "tenant_id": self.tenant_id,
            "origin_store_id": self.origin_store_id,
            "verdict": self.verdict.value,
            "integrity_revision": self.integrity_revision,
            "issued_at_ms": self.issued_at_ms,
            "expires_at_ms": self.expires_at_ms,
            "policy_id": self.policy_id,
        }


# Reason codes. Stable strings, because an operator filters on them and an audit
# trail outlives whatever phrasing seemed clear at the time.
ACTIVE = "active"
NOT_FOUND = "not_found"
BLOCKED_LIFECYCLE = "blocked_lifecycle"
CONTESTED = "contested"
CANDIDATE_UNVALIDATED = "candidate_unvalidated"
WITHDRAWN_ON_WEAK_EVIDENCE = "withdrawn_on_weak_evidence"
VERSION_MOVED = "version_moved"
TOKEN_EXPIRED = "token_expired"
INTEGRITY_MOVED = "integrity_moved"
WRONG_AGENT = "wrong_agent"
WRONG_STORE = "wrong_store"
WRONG_TENANT = "wrong_tenant"


class Enforcer:
    """The single layer every supported read goes through."""

    def __init__(self, fabric: Any, token_ttl_ms: int | None = 300_000) -> None:
        self.fabric = fabric
        self.token_ttl_ms = token_ttl_ms

    # --- the check -------------------------------------------------------

    def check(
        self,
        memory_id: str,
        risk: RiskLevel = RiskLevel.LOW,
        include_contested: bool = False,
        tenant_id: str | None = None,
    ) -> AccessDecision:
        """Resolve tenant, then lifecycle, then decide by risk.

        The order is deliberate: establish what is *known* about the memory
        before asking what the caller intends to do with it, so the same facts
        produce the same `reason_code` at every risk level and only the verdict
        moves.

        The tenant comes first within that, and before the lifecycle, because a
        cross-tenant request must not be answered with a fact about the other
        tenant's memory. "Withdrawn on weak evidence" is a true and useful
        reason code and it is also a statement that the memory exists and what
        was done to it, which a caller from another tenant has no business
        learning. `tenant_id` None means the caller is not tenant-scoped at all
        — the operator path — and is not the same as matching every tenant by
        accident.
        """
        state = self.fabric.state
        memory = state.memories.get(memory_id)
        revision = self.fabric.log.head_seq

        if memory is None:
            return AccessDecision(
                memory_id=memory_id, version=0, verdict=Verdict.DENY,
                reason_code=NOT_FOUND, risk=risk, integrity_revision=revision,
            )

        if tenant_id is not None and memory.tenant_id != tenant_id \
                and getattr(self.fabric, "conceal_cross_tenant", False):
            # Indistinguishable from a missing id: same verdict, code, version.
            return AccessDecision(
                memory_id=memory_id, version=0, verdict=Verdict.DENY,
                reason_code=NOT_FOUND, risk=risk, integrity_revision=revision,
            )
        if tenant_id is not None and memory.tenant_id != tenant_id:
            # No `detail`, and the version is reported as 0: the refusal says
            # only "not yours", which is all a caller in another tenant may
            # learn. A reason code naming the owning tenant would turn this
            # check into an enumeration oracle.
            return AccessDecision(
                memory_id=memory_id, version=0, verdict=Verdict.DENY,
                reason_code=WRONG_TENANT, risk=risk, integrity_revision=revision,
            )

        lifecycle = memory.lifecycle_state
        common = {
            "memory_id": memory_id,
            "version": memory.version,
            "lifecycle_state": lifecycle.value,
            "risk": risk,
            "integrity_revision": revision,
        }

        if lifecycle in BLOCKED_STATES:
            basis = state.withdrawal_basis.get(memory_id, "")
            if basis in {b.value for b in WEAK_BASES}:
                # Still denied — the memory *is* withdrawn — but the reason says
                # the withdrawal itself is the suspect thing, so an operator is
                # pointed at releasing it rather than at the memory.
                return AccessDecision(
                    **common, verdict=Verdict.DENY,
                    reason_code=WITHDRAWN_ON_WEAK_EVIDENCE,
                    detail=f"withdrawn on '{basis}', which does not support a withdrawal alone",
                )
            return AccessDecision(
                **common, verdict=Verdict.DENY, reason_code=BLOCKED_LIFECYCLE,
                detail=f"lifecycle is {lifecycle.value}",
            )

        if lifecycle is LifecycleState.CANDIDATE:
            return AccessDecision(
                **common,
                verdict=Verdict.DENY if risk is RiskLevel.HIGH else Verdict.REVALIDATE,
                reason_code=CANDIDATE_UNVALIDATED,
                detail="never validated; a candidate is not usable memory",
            )

        if lifecycle in EXPLORATORY_STATES:
            # Contested: a real disagreement. Low risk may proceed with a
            # warning, medium needs someone to resolve it, high must not stake
            # a consequential action on an open question.
            verdict = {
                RiskLevel.LOW: Verdict.WARN,
                RiskLevel.MEDIUM: Verdict.REVALIDATE,
                RiskLevel.HIGH: Verdict.DENY,
            }[risk]
            if not include_contested and verdict is Verdict.WARN:
                verdict = Verdict.REVALIDATE
            return AccessDecision(
                **common, verdict=verdict, reason_code=CONTESTED,
                detail="a conflicting memory exists and the conflict is unresolved",
            )

        if lifecycle in EXPOSABLE_STATES:
            return AccessDecision(**common, verdict=Verdict.USABLE, reason_code=ACTIVE)

        # A state the enforcer does not model. Fail closed rather than guess:
        # an unmodelled state is unknown integrity, and unknown is a refusal.
        return AccessDecision(
            **common, verdict=Verdict.UNKNOWN, reason_code=BLOCKED_LIFECYCLE,
            detail=f"unmodelled lifecycle state {lifecycle.value}",
        )

    # --- tokens ----------------------------------------------------------

    def issue(
        self,
        memory_id: str,
        agent_id: str,
        decision: AccessDecision,
        policy_id: str = "",
        tenant_id: str | None = None,
    ) -> ExposureToken:
        from .federation import imported_from

        now = self.fabric.now()
        origin = imported_from(self.fabric, memory_id)
        return ExposureToken(
            memory_id=memory_id,
            version=decision.version,
            agent_id=agent_id,
            store_id=self.fabric.store_id,
            tenant_id=tenant_id,
            origin_store_id=None if origin is None else origin.get("store"),
            verdict=decision.verdict,
            integrity_revision=decision.integrity_revision,
            issued_at_ms=now,
            expires_at_ms=None if self.token_ttl_ms is None else now + self.token_ttl_ms,
            policy_id=policy_id,
        )

    def verify_at_action(
        self, token: ExposureToken, agent_id: str, risk: RiskLevel = RiskLevel.HIGH
    ) -> AccessDecision:
        """Re-check immediately before a consequential action.

        This is the time-of-check/time-of-use defence. Retrieval may have
        happened seconds or minutes ago; a retraction may have arrived since.
        Re-running the check is cheap — it reads projections — and the
        alternative is acting on knowledge whose author has withdrawn it.

        Defaults to `HIGH` because the only reason to call this is that
        something consequential is about to happen.
        """
        revision = self.fabric.log.head_seq

        if token.store_id != self.fabric.store_id:
            return AccessDecision(
                memory_id=token.memory_id, version=token.version,
                verdict=Verdict.DENY, reason_code=WRONG_STORE, risk=risk,
                integrity_revision=revision,
                detail="token was issued by a different store",
            )
        if token.agent_id != agent_id:
            # A token is not a bearer credential to be passed around.
            return AccessDecision(
                memory_id=token.memory_id, version=token.version,
                verdict=Verdict.DENY, reason_code=WRONG_AGENT, risk=risk,
                integrity_revision=revision,
                detail="token was issued to a different agent",
            )
        if token.expired(self.fabric.now()):
            return AccessDecision(
                memory_id=token.memory_id, version=token.version,
                verdict=Verdict.DENY, reason_code=TOKEN_EXPIRED, risk=risk,
                integrity_revision=revision,
                detail="exposure token has expired; retrieve again",
            )

        decision = self.check(token.memory_id, risk=risk, tenant_id=token.tenant_id)
        if decision.reason_code == WRONG_TENANT:
            # Return the tenant refusal as it stands. The version comparison
            # below would otherwise fire first and report `version_moved`,
            # because a cross-tenant check deliberately reports version 0 — so
            # the refusal would be correct and its stated reason would be a
            # fiction, which is the worse of the two failures in an audit.
            return decision
        if decision.version != token.version:
            # The memory was revised. The token's decision was about a different
            # version, so it says nothing about this one.
            return AccessDecision(
                memory_id=token.memory_id, version=decision.version,
                verdict=Verdict.REVALIDATE, reason_code=VERSION_MOVED, risk=risk,
                integrity_revision=revision,
                lifecycle_state=decision.lifecycle_state,
                detail=f"token was issued for v{token.version}, store holds v{decision.version}",
            )
        if decision.verdict is not Verdict.USABLE and token.verdict is Verdict.USABLE:
            # The common case this exists for: usable at retrieval, retracted
            # since. Return the *current* decision, not the token's.
            return AccessDecision(
                memory_id=decision.memory_id, version=decision.version,
                verdict=decision.verdict,
                reason_code=decision.reason_code or INTEGRITY_MOVED,
                risk=risk, integrity_revision=revision,
                lifecycle_state=decision.lifecycle_state,
                detail=decision.detail or "integrity state changed after retrieval",
            )
        return decision


@dataclass
class EnforcedRead:
    """What an enforced read returns: the decision, a token, and the memory only
    when the decision allows it."""

    decision: AccessDecision
    token: ExposureToken | None = None
    memory: Any = None
    warnings: list[str] = field(default_factory=list)

    @property
    def usable(self) -> bool:
        return self.decision.usable and self.memory is not None
