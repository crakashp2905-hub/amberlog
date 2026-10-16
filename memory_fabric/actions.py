"""Action-time verification: the gate in front of a protected tool (plan Task 4).

Two questions are kept apart, because the plan's invariant is that *memory
validity is not action authorisation*:

1. **May this agent use this tool at all?** Answered from the gate's own grant
   table, configured by the host. Nothing an agent writes, retrieves or
   certifies can add a tool to its grants.
2. **Is the evidence for this action still good?** Answered by re-verifying an
   `EvidenceCertificate` against the store, immediately before the action.

The tool grant is checked first, so an ungranted call is refused without
touching memory at all and a perfect certificate cannot rescue it. A protected
tool without a certificate is refused. A tool rule can require stronger checks
than the certificate declares; it can never be weakened by one, because the
verifier runs the *union* of the rule's checks and the certificate's.

**Service-unavailable behaviour.** If the store cannot be read, a protected
action is refused with `state_unavailable`. An unprotected tool does not depend
on memory and is not blocked by a memory outage. Unknown tools are refused.

**Audit.** Every decision on a protected tool appends an `ActionGated` event:
the tool, the agent, the verdict, the reason codes, the certificate digest and
the evidence ids and versions. Never content. This is the link Task 9 needs
from evidence to action.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Mapping

from . import events as ev
from .certificates import (
    ALWAYS,
    CertificateError,
    CertificateVerification,
    CertificateVerifier,
    EvidenceCertificate,
    STATE_UNAVAILABLE,
)
from .enforcement import RiskLevel

ACTION_POLICY_VERSION = "action-policy-v1"

# Reason codes.
ALLOWED = "allowed"
UNPROTECTED = "unprotected_tool"
UNKNOWN_TOOL = "unknown_tool"
TOOL_NOT_GRANTED = "tool_not_granted"
CERTIFICATE_REQUIRED = "certificate_required"
HUMAN_APPROVAL_REQUIRED = "human_approval_required"
APPROVAL_INVALID = "approval_invalid"
CREDENTIAL_INVALID = "credential_invalid"


@dataclass(frozen=True)
class ToolRule:
    """How one tool is governed. `protected` tools need a valid certificate."""

    name: str
    protected: bool = True
    required_checks: tuple[str, ...] = ALWAYS
    min_independent_sources: int = 1
    requires_human_approval: bool = False


@dataclass(frozen=True)
class ActionPolicy:
    """The host's configuration. Agents never supply any of it."""

    tools: Mapping[str, ToolRule]
    grants: Mapping[str, frozenset[str]]
    """agent_id -> tool names that agent may call."""

    approvers: frozenset[str] = frozenset()
    policy_id: str = ACTION_POLICY_VERSION


@dataclass(frozen=True)
class Approval:
    """A human's approval, bound to one exact certificate."""

    approver_id: str
    certificate_digest: str


@dataclass(frozen=True)
class ActionDecision:
    allowed: bool
    tool: str
    agent_id: str
    reason_codes: tuple[str, ...]
    verification: CertificateVerification | None = None
    notes: tuple[str, ...] = field(default_factory=tuple)

    @property
    def reason_code(self) -> str:
        return self.reason_codes[0]


class ActionGate:
    """Decides, immediately before a tool runs, whether it may run."""

    def __init__(
        self,
        fabric: Any,
        policy: ActionPolicy,
        mode: str = "selective",
        audit: bool = True,
    ) -> None:
        self.fabric = fabric
        self.policy = policy
        self.verifier = CertificateVerifier(fabric, mode=mode)
        self.audit = audit

    def authorize(
        self,
        tool: str,
        agent_id: str,
        certificate: EvidenceCertificate | Mapping[str, Any] | None = None,
        tenant_id: str | None = None,
        approval: Approval | None = None,
        session: Any = None,
    ) -> ActionDecision:
        """Return whether `agent_id` may call `tool` now.

        With `session` (a `service.Session`), the caller's identity and tenant
        come from its credential, which is re-verified here: a credential
        revoked since retrieval stops the action (authorisation drift, S13).
        """
        if session is not None:
            try:
                principal = session.principal()
            except Exception:
                return self._decide(tool, agent_id, (CREDENTIAL_INVALID,), None, None)
            agent_id, tenant_id = principal.agent_id, principal.tenant_id

        rule = self.policy.tools.get(tool)
        if rule is None:
            return self._decide(tool, agent_id, (UNKNOWN_TOOL,), None, None)
        if tool not in self.policy.grants.get(agent_id, frozenset()):
            # Before any memory is consulted. A valid certificate is evidence,
            # not permission.
            return self._decide(tool, agent_id, (TOOL_NOT_GRANTED,), None, rule)
        if not rule.protected:
            return self._decide(tool, agent_id, (UNPROTECTED,), None, rule, allowed=True)
        if certificate is None:
            return self._decide(tool, agent_id, (CERTIFICATE_REQUIRED,), None, rule)

        if not isinstance(certificate, EvidenceCertificate):
            try:
                certificate = EvidenceCertificate.from_json(certificate)
            except CertificateError as exc:
                return self._decide(tool, agent_id, (exc.reason_code,), None, rule)
        # The rule can strengthen the certificate's checks, never the reverse.
        strengthened = replace(
            certificate,
            required_checks=tuple(dict.fromkeys(
                [*certificate.required_checks, *rule.required_checks])),
            min_independent_sources=max(certificate.min_independent_sources,
                                        rule.min_independent_sources),
        )
        verification = self.verifier.verify(
            strengthened, agent_id=agent_id, tenant_id=tenant_id, risk=RiskLevel.HIGH)
        if not verification.ok:
            return self._decide(tool, agent_id, verification.reason_codes,
                                verification, rule, certificate=certificate)

        if rule.requires_human_approval:
            if approval is None:
                return self._decide(tool, agent_id, (HUMAN_APPROVAL_REQUIRED,),
                                    verification, rule, certificate=certificate)
            if (approval.approver_id not in self.policy.approvers
                    or approval.approver_id == agent_id
                    or approval.certificate_digest != certificate.digest()):
                return self._decide(tool, agent_id, (APPROVAL_INVALID,),
                                    verification, rule, certificate=certificate)

        return self._decide(tool, agent_id, (ALLOWED,), verification, rule,
                            allowed=True, certificate=certificate)

    # --- audit -----------------------------------------------------------

    def _decide(
        self,
        tool: str,
        agent_id: str,
        reasons: tuple[str, ...],
        verification: CertificateVerification | None,
        rule: ToolRule | None,
        allowed: bool = False,
        certificate: EvidenceCertificate | None = None,
    ) -> ActionDecision:
        decision = ActionDecision(
            allowed=allowed, tool=tool, agent_id=agent_id,
            reason_codes=reasons, verification=verification,
        )
        if self.audit and (rule is None or rule.protected):
            try:
                self.fabric._emit(ev.action_gated(
                    ts=self.fabric.now(),
                    agent_id=agent_id,
                    tool=tool,
                    allowed=allowed,
                    reason_codes=list(reasons),
                    policy_id=self.policy.policy_id,
                    claim_id=certificate.claim_id if certificate else None,
                    certificate_digest=certificate.digest() if certificate else None,
                    evidence=[[e.memory_id, e.version] for e in certificate.evidence]
                    if certificate else [],
                    watermark=verification.verified_at_watermark if verification else None,
                ))
            except Exception:
                # An audit write that fails must not turn a refusal into an
                # allow, and must not let an allow proceed unrecorded.
                if allowed:
                    return ActionDecision(
                        allowed=False, tool=tool, agent_id=agent_id,
                        reason_codes=(STATE_UNAVAILABLE,), verification=verification,
                        notes=("audit write failed",),
                    )
        return decision
