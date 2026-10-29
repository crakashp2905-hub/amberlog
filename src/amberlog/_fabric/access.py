"""Reads and inspection: the enforced read, action-time verification, certificates, history, lineage, explanations, audit trail and health.

A service mixin of `Amberlog`, built on `FabricCore`. Methods moved here
verbatim from `fabric.py`.
"""

from __future__ import annotations

__stability__ = "stable"



from typing import TYPE_CHECKING, Any, Sequence, cast

if TYPE_CHECKING:
    from ..fabric import Amberlog  # noqa: F401
    from ..explain import Explanation  # pragma: no cover
    from ..certificates import CertificateVerification, EvidenceCertificate

from .. import events as ev
from ..lineage import LineageView

from ..enforcement import (
    AccessDecision,
    EnforcedRead,
    ExposureToken,
    RiskLevel,
    Verdict,
)
from ..model import (
    LifecycleState,
    Memory,
)


from .core import FabricCore
from .common import HealthReport, _fresh


class AccessMixin(FabricCore):

    @_fresh
    def get(self, memory_id: str) -> Memory:
        """**Inspection only. Not an agent-facing read.**

        Returns a memory whatever its lifecycle state, which is correct for an
        operator tool asking "what is this and why was it withdrawn?" and wrong
        for anything that will put the content in front of a model. Phase 0's
        audit found this was the one way to reach past the lifecycle check
        without knowing it.

        The enforced read is `use()`. Supported adapters must call that; this
        exists for `explain`, the dashboard and the CLI, none of which hand
        memories to an agent.
        """
        return self._require(memory_id)

    @_fresh
    def lifecycle_of(self, memory_id: str) -> LifecycleState:
        """One memory's lifecycle state, and **no content**.

        Exists because the adapters wanted to tell a model what happened to its
        own write and were reaching for `get()` to do it. `get()` returns a
        withdrawn memory on purpose — an operator judging a withdrawal has to
        read what was withdrawn — so an adapter holding it is one autocomplete
        away from serving retracted knowledge to a model, and it would look
        like working code.

        Found by the data-access audit, which flagged every `fabric.get(` in
        the shipped examples and adapters.
        """
        return self._require(memory_id).lifecycle_state

    def tenant_of(self, memory_id: str) -> str:
        return self._require(memory_id).tenant_id

    @_fresh
    def tenants(self) -> dict[str, int]:
        """Which tenants this store holds, and how many memories each has.

        An operator view. It is also the thing a `doctor` check needs in order
        to notice that a store believed to be single-tenant is not.
        """
        counts: dict[str, int] = {}
        for memory in self.state.memories.values():
            counts[memory.tenant_id] = counts.get(memory.tenant_id, 0) + 1
        return dict(sorted(counts.items()))

    @_fresh
    def use(
        self,
        memory_id: str,
        agent_id: str,
        risk: "RiskLevel" = RiskLevel.LOW,
        include_contested: bool = False,
        audit: bool = True,
        tenant_id: str | None = None,
    ) -> "EnforcedRead":
        """The enforced read: one layer, and a token that can be re-checked.

        Returns the memory only when the decision allows it, so a caller that
        ignores the decision still cannot act on withdrawn knowledge. A refusal
        is audited without the content (see `ev.access_denied`).
        """
        decision = self.enforcer.check(
            memory_id, risk=risk, include_contested=include_contested,
            tenant_id=tenant_id, agent_id=agent_id,
        )
        if not decision.usable:
            if audit:
                self._emit(
                    ev.access_denied(
                        ts=self.now(),
                        memory_id=memory_id,
                        version=decision.version,
                        agent_id=agent_id,
                        verdict=decision.verdict.value,
                        reason_code=decision.reason_code,
                        risk=risk.value,
                        detail=decision.detail,
                    )
                )
            return EnforcedRead(decision=decision)

        memory = self.state.memories[memory_id]
        token = self.enforcer.issue(
            memory_id, agent_id, decision, policy_id=self.policy.id,
            tenant_id=tenant_id,
        )
        warnings = [decision.detail] if decision.verdict is Verdict.WARN and decision.detail else []
        return EnforcedRead(
            decision=decision, token=token, memory=memory, warnings=warnings
        )

    @_fresh
    def verify_before_action(
        self,
        token: "ExposureToken",
        agent_id: str,
        risk: "RiskLevel" = RiskLevel.HIGH,
        audit: bool = True,
    ) -> "AccessDecision":
        """Re-check immediately before a consequential action.

        The time-of-check/time-of-use defence. Retrieval may have been minutes
        ago and a retraction may have arrived since; re-running the check reads
        projections and is cheap, and the alternative is acting on knowledge its
        author has withdrawn.
        """
        decision = self.enforcer.verify_at_action(token, agent_id, risk=risk)
        if not decision.usable and audit:
            self._emit(
                ev.access_denied(
                    ts=self.now(),
                    memory_id=decision.memory_id,
                    version=decision.version,
                    agent_id=agent_id,
                    verdict=decision.verdict.value,
                    reason_code=decision.reason_code,
                    risk=risk.value,
                    detail=decision.detail,
                )
            )
        return decision

    @_fresh
    def certify(
        self,
        claim_id: str,
        evidence: Sequence[Any],
        agent_id: str,
        tenant_id: str | None = None,
        required_checks: Sequence[str] = (),
        min_independent_sources: int = 1,
        ttl_ms: int | None = 300_000,
    ) -> "EvidenceCertificate":
        """Record the evidence a decision rests on, for re-checking at action
        time (`certificates.py`). Issuing checks nothing; `verify_certificate`
        does, against the store as it is then."""
        from ..certificates import ALWAYS, CertificateVerifier

        return CertificateVerifier(self).issue(
            claim_id, evidence, agent_id, tenant_id=tenant_id,
            required_checks=tuple(required_checks) or ALWAYS,
            min_independent_sources=min_independent_sources, ttl_ms=ttl_ms,
        )

    @_fresh
    def verify_certificate(
        self,
        certificate: Any,
        agent_id: str,
        tenant_id: str | None = None,
        risk: "RiskLevel" = RiskLevel.HIGH,
        mode: str = "selective",
    ) -> "CertificateVerification":
        """Re-check every piece of evidence in a certificate, now. Fails closed."""
        from ..certificates import CertificateVerifier

        return CertificateVerifier(self, mode=mode).verify(
            certificate, agent_id=agent_id, tenant_id=tenant_id, risk=risk)

    @_fresh
    def history(self, memory_id: str) -> list[Memory]:
        self._require(memory_id)
        return list(self.state.history.get(memory_id, ())) + [self.state.memories[memory_id]]

    @_fresh
    def lineage(self, memory_id: str) -> LineageView:
        self._require(memory_id)
        return self.lineage_graph.view(memory_id)

    @_fresh
    def audit_trail(self, memory_id: str) -> list[ev.Event]:
        """Every event that mentions this memory, in log order."""
        self._require(memory_id)
        out: list[ev.Event] = []
        for event in self.log.read():
            payload = event.payload
            if payload.get("memory_id") == memory_id:
                out.append(event)
            elif memory_id in (payload.get("memory_ids") or ()):
                out.append(event)
            elif isinstance(payload.get("memory"), dict) and payload["memory"].get("id") == memory_id:
                out.append(event)
            elif any(
                c.get("memory_id") == memory_id for c in (payload.get("candidates") or ())
            ):
                out.append(event)
        return out

    @_fresh
    def explain(self, memory_id: str) -> "Explanation":
        from ..explain import explain_memory

        return explain_memory(cast("Amberlog", self), memory_id)

    @_fresh
    def health(self) -> HealthReport:
        by_state: dict[str, int] = {}
        by_scope: dict[str, int] = {}
        by_type: dict[str, int] = {}
        unverified = never_exposed = 0
        self._refresh_estimator()
        for memory in self.state.memories.values():
            by_state[memory.lifecycle_state.value] = by_state.get(memory.lifecycle_state.value, 0) + 1
            by_scope[memory.scope.value] = by_scope.get(memory.scope.value, 0) + 1
            by_type[memory.type.value] = by_type.get(memory.type.value, 0) + 1
            stats = self.state.stats_for(memory.id)
            # The live estimate, not the projected one. `stats.value_estimate` is
            # only populated by value(persist=True), so counting it here would
            # report every memory as unverified in the normal case and contradict
            # anything that asks the estimator directly.
            if self.estimator.estimate(memory.id).n_eff <= 0.0:
                unverified += 1
            if stats.exposures == 0:
                never_exposed += 1
        return HealthReport(
            total=len(self.state.memories),
            by_state=by_state,
            by_scope=by_scope,
            by_type=by_type,
            unverified=unverified,
            contested=by_state.get(LifecycleState.CONTESTED.value, 0),
            quarantined=by_state.get(LifecycleState.QUARANTINED.value, 0),
            never_exposed=never_exposed,
            open_hypothesis_sets=sum(
                1 for h in self.state.hypothesis_sets.values() if not h.resolved
            ),
            episodes=len(self.state.episodes),
            episodes_with_outcome=sum(1 for e in self.state.episodes.values() if e.has_outcome),
            events=len(self.log),
        )
