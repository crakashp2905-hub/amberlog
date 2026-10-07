"""The memory firewall: the boundary between local and collective learning.

Implements SPEC.md section 7. Default-deny on scope promotion. Each rule returns
a decision and a reason, and the strictest decision wins, so a ruling always
carries the full list of reasons for the audit trail.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Iterable, Sequence

from ..model import (
    FirewallDecision,
    LifecycleState,
    Memory,
    MemoryType,
    Scope,
    SecurityClass,
    ValueEstimate,
)
from .sensitive import SensitiveDataDetector, summarise

# Strictest last: used to pick the governing decision.
_SEVERITY = [
    FirewallDecision.ALLOW,
    FirewallDecision.ALLOW_WITH_WARNING,
    FirewallDecision.REQUIRE_VALIDATION,
    FirewallDecision.QUARANTINE,
    FirewallDecision.DENY,
]


@dataclass
class FirewallRuling:
    decision: FirewallDecision
    reasons: list[str] = field(default_factory=list)

    @property
    def permits_sharing(self) -> bool:
        return self.decision.permits_sharing

    def __str__(self) -> str:
        return f"{self.decision.value}: {'; '.join(self.reasons) or 'no findings'}"


@dataclass
class FirewallRequest:
    memory: Memory
    target_scope: Scope
    value: ValueEstimate | None = None
    hypothesis_open: bool = False
    granted_capabilities: frozenset[str] = frozenset()
    evidence_independent: bool = True


Rule = Callable[[FirewallRequest], tuple[FirewallDecision, str] | None]


def rule_restricted_stays_private(request: FirewallRequest) -> tuple[FirewallDecision, str] | None:
    if (
        request.memory.security_class is SecurityClass.RESTRICTED
        and request.target_scope is not Scope.PRIVATE
    ):
        return FirewallDecision.DENY, "security_class=restricted may not leave private scope"
    return None


def rule_must_be_active(request: FirewallRequest) -> tuple[FirewallDecision, str] | None:
    state = request.memory.lifecycle_state
    if state is LifecycleState.ACTIVE:
        return None
    if state is LifecycleState.CONTESTED:
        # Contested memories can still travel, but never silently: the reason
        # is recorded and the caller is expected to carry the siblings.
        return (
            FirewallDecision.ALLOW_WITH_WARNING,
            "memory is contested; hypothesis-set siblings must travel with it",
        )
    return FirewallDecision.DENY, f"lifecycle_state={state.value} is not shareable"


def rule_value_must_show_benefit(request: FirewallRequest) -> tuple[FirewallDecision, str] | None:
    """Scope promotion requires evidence of benefit, not just absence of harm.

    An unknown value is not a denial. It is the normal state of a new memory in a
    deployment with no outcome signal, which product-first assumes is the common
    case, so the rule asks for validation instead of blocking.

    A non-contrastive estimate is also not evidence. A high average outcome on
    episodes where a memory happened to be retrieved is the exact confusion
    between value and relevance that this system exists to avoid, so it is
    reported as insufficient rather than silently accepted.
    """
    if request.target_scope.rank <= Scope.PRIVATE.rank:
        return None
    value = request.value
    if value is None or value.n_eff <= 0.0:
        return FirewallDecision.REQUIRE_VALIDATION, "no value evidence yet"
    if not value.contrastive:
        return (
            FirewallDecision.REQUIRE_VALIDATION,
            f"estimator {value.estimator!r} is not contrastive; an absolute outcome rate "
            "cannot establish that this memory helps",
        )
    if not value.shows_benefit:
        return (
            FirewallDecision.REQUIRE_VALIDATION,
            f"value lower bound {value.ci_low:+.3f} does not clear zero",
        )
    return None


def rule_open_hypothesis_warns(request: FirewallRequest) -> tuple[FirewallDecision, str] | None:
    if request.hypothesis_open:
        return (
            FirewallDecision.ALLOW_WITH_WARNING,
            f"member of unresolved hypothesis set {request.memory.hypothesis_set}",
        )
    return None


def rule_capabilities_must_be_granted(request: FirewallRequest) -> tuple[FirewallDecision, str] | None:
    """A federated procedure is code that runs with the recipient's tools
    (SECURITY.md T4), so capability scoping is a denial, not a warning."""
    if request.memory.type is not MemoryType.PROCEDURAL:
        return None
    if request.target_scope is Scope.PRIVATE:
        return None
    ungranted = sorted(set(request.memory.capabilities) - set(request.granted_capabilities))
    if ungranted:
        return (
            FirewallDecision.DENY,
            f"procedure requires ungranted capabilities: {', '.join(ungranted)}",
        )
    return None


def rule_evidence_independence(request: FirewallRequest) -> tuple[FirewallDecision, str] | None:
    if not request.evidence_independent and request.target_scope is Scope.FEDERATED:
        return (
            FirewallDecision.REQUIRE_VALIDATION,
            "supporting evidence shares ancestry; confirmations are not independent",
        )
    return None


DEFAULT_RULES: tuple[Rule, ...] = (
    rule_restricted_stays_private,
    rule_must_be_active,
    rule_value_must_show_benefit,
    rule_open_hypothesis_warns,
    rule_capabilities_must_be_granted,
    rule_evidence_independence,
)


class Firewall:
    """Rule-based, deterministic, and explainable. A learned policy could
    replace it later, but the audit trail requires stated reasons either way."""

    id = "firewall_v0"

    def __init__(
        self,
        rules: Sequence[Rule] | None = None,
        detector: SensitiveDataDetector | None = None,
    ) -> None:
        self.rules = tuple(rules) if rules is not None else DEFAULT_RULES
        self.detector = detector or SensitiveDataDetector()

    def evaluate(self, request: FirewallRequest) -> FirewallRuling:
        decisions: list[FirewallDecision] = [FirewallDecision.ALLOW]
        reasons: list[str] = []

        for rule in self.rules:
            result = rule(request)
            if result is None:
                continue
            decision, reason = result
            decisions.append(decision)
            reasons.append(reason)

        findings = self.detector.scan(request.memory.content)
        if findings:
            decisions.append(FirewallDecision.QUARANTINE)
            reasons.append(f"sensitive data detected: {summarise(findings)}")

        governing = max(decisions, key=_SEVERITY.index)
        return FirewallRuling(decision=governing, reasons=reasons)

    def screen_ingest(self, content: str) -> FirewallRuling:
        """Cheaper check for the write path: content only, no scope decision."""
        findings = self.detector.scan(content)
        if any(f.severity == "high" for f in findings):
            return FirewallRuling(
                FirewallDecision.QUARANTINE,
                [f"sensitive data detected on ingest: {summarise(findings)}"],
            )
        if findings:
            return FirewallRuling(
                FirewallDecision.ALLOW_WITH_WARNING,
                [f"possible sensitive data on ingest: {summarise(findings)}"],
            )
        return FirewallRuling(FirewallDecision.ALLOW, [])


def strictest(decisions: Iterable[FirewallDecision]) -> FirewallDecision:
    return max(decisions, key=_SEVERITY.index)
