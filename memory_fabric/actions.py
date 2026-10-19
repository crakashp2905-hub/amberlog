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

## The fence: closing the window between "verified" and "done" (S6)

`authorize` answers "may this run now?", and the answer is stale the moment it
returns. A retraction committed after `verify` and before the tool's side
effect was not seen. That is threat S14, which was accepted as a residual race.

`execute` closes it for a tool the store can wait on. Verification and the
tool run inside **one store write transaction** (`BEGIN IMMEDIATE`, plus the
in-process lock), so no retraction, quarantine or revocation can commit
between them. A concurrent writer in this process or any other waits for the
action, and then commits after it. The outcome is linearisable: every action
happened either before a withdrawal of its evidence or not at all. Readers are
not blocked, because the log is in WAL mode.

The price and the limits, stated:

- **Writers wait** up to the lease. A writer in another process waits up to
  its SQLite busy timeout (5 s by default), so `lease_s` must stay below it,
  or that writer fails with "database is locked" and must retry. `execute`
  refuses a lease at or above `MAX_LEASE_S`.
- **A tool that overruns its lease** has the fence released, so a hung tool
  cannot stop every write to the store. The call returns `timed_out`, the
  record says `fenced: false`, and `unfenced_changes()` reports any change to
  the evidence after that point. The window is bounded and recorded, not
  closed.
- **The tool must not call this store.** It runs on a worker thread while the
  caller holds the store's lock, so a store call from inside it waits until
  the lease runs out.
- **A crash mid-action** rolls the transaction back, so neither the decision
  nor the outcome is recorded. The tool receives the idempotency key so that
  it, the only party that can know, deduplicates a retry.
- **Retry.** A key whose last attempt `executed` is not run again
  (`already_executed`). One that `timed_out` or `failed` has an unknown
  effect, so it runs again only with `retry=True`, and then it re-verifies
  from scratch. A stale verification is never reused.
"""

from __future__ import annotations

__stability__ = "beta"

import threading
import time
from dataclasses import dataclass, field, replace
from typing import Any, Callable, Mapping

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
RETRY_REQUIRED = "retry_required"
AUTHORITY_INSUFFICIENT = "authority_insufficient"
INSTRUCTION_EVIDENCE = "instruction_is_not_evidence"
GRANT_REQUIRED = "grant_required"
GRANT_UNKNOWN = "grant_unknown"
GRANT_EXPIRED = "grant_expired"
GRANT_REVOKED = "grant_revoked"
GRANT_MISMATCH = "grant_binding_mismatch"
GRANT_REPLAYED = "grant_replayed"
MAX_GRANT_TTL_S = 300

# Execution outcomes (`execute`).
EXECUTED = "executed"
FAILED = "failed"
TIMED_OUT = "timed_out"
ALREADY_EXECUTED = "already_executed"
REFUSED = "refused"

MAX_LEASE_S = 4.0
"""Below the store's default 5 s busy timeout, so a writer in another process
waiting on the fence gets in before it gives up."""


@dataclass(frozen=True)
class ToolRule:
    """How one tool is governed. `protected` tools need a valid certificate."""

    name: str
    protected: bool = True
    required_checks: tuple[str, ...] = ALWAYS
    min_independent_sources: int = 1
    requires_human_approval: bool = False
    min_authority: str = "unverified"
    """The lowest origin-bound trust (`authority.py`) any piece of evidence
    may have. `unverified` refuses evidence descending from a tool output, an
    import, a hostile source, an instruction or a withdrawn memory, unless an
    approver elevated it. `untrusted` turns the check off."""
    requires_grant: bool = False
    """Require a short-lived grant bound to this exact action (`issue_grant`)."""


@dataclass(frozen=True)
class ActionRequest:
    """The exact action: what it acts on and with which parameters."""

    target: str
    parameters: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Grant:
    grant_id: str
    tool: str
    agent_id: str
    binding: str
    expires_ms: int


def binding_digest(tool: str, agent_id: str, tenant_id: str | None,
                   request: ActionRequest | None,
                   certificate: EvidenceCertificate | None) -> str:
    """Digest of everything an approval or grant is for. Any change is a different action."""
    import hashlib
    import json

    body = {"tool": tool, "agent": agent_id, "tenant": tenant_id,
            "target": request.target if request else None,
            "parameters": dict(request.parameters) if request else None,
            "evidence": sorted([e.memory_id, e.version] for e in certificate.evidence)
            if certificate else []}
    return hashlib.sha256(json.dumps(body, sort_keys=True, default=str,
                                     separators=(",", ":")).encode()).hexdigest()


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
    binding: str | None = None
    """When set, the approval covers only the action with this
    `binding_digest`: a changed target or parameter voids it."""


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


@dataclass(frozen=True)
class ActionExecution:
    """What `ActionGate.execute` did."""

    outcome: str
    decision: ActionDecision | None
    key: str
    result: Any = None
    error: str | None = None
    fenced: bool = True

    @property
    def ran(self) -> bool:
        return self.outcome in (EXECUTED, FAILED, TIMED_OUT)


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
        request: ActionRequest | None = None,
        grant: Grant | str | None = None,
    ) -> ActionDecision:
        """Return whether `agent_id` may call `tool` now.

        Fail-closed order: identity, tool grant, certificate, evidence
        re-verification, origin-bound authority of every piece of evidence,
        human approval, then the exact-action grant. `request` names the
        target and parameters; approvals and grants are bound to them.

        With `session` (a `service.Session`), the caller's identity and tenant
        come from its credential, which is re-verified here: a credential
        revoked since retrieval stops the action (authorisation drift, S13).
        """
        if session is not None:
            try:
                principal = session.principal()
            except Exception:
                return self._decide(tool, agent_id, (CREDENTIAL_INVALID,), None, None, tenant_id=tenant_id)
            agent_id, tenant_id = principal.agent_id, principal.tenant_id

        rule = self.policy.tools.get(tool)
        if rule is None:
            return self._decide(tool, agent_id, (UNKNOWN_TOOL,), None, None, tenant_id=tenant_id)
        if tool not in self.policy.grants.get(agent_id, frozenset()):
            # Before any memory is consulted. A valid certificate is evidence,
            # not permission.
            return self._decide(tool, agent_id, (TOOL_NOT_GRANTED,), None, rule, tenant_id=tenant_id)
        if not rule.protected:
            return self._decide(tool, agent_id, (UNPROTECTED,), None, rule, allowed=True, tenant_id=tenant_id)
        if certificate is None:
            return self._decide(tool, agent_id, (CERTIFICATE_REQUIRED,), None, rule, tenant_id=tenant_id)

        if not isinstance(certificate, EvidenceCertificate):
            try:
                certificate = EvidenceCertificate.from_json(certificate)
            except CertificateError as exc:
                return self._decide(tool, agent_id, (exc.reason_code,), None, rule, tenant_id=tenant_id)
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
                                verification, rule, certificate=certificate, tenant_id=tenant_id)
        authority_reason = self._authority(certificate, rule)
        if authority_reason:
            return self._decide(tool, agent_id, (authority_reason,), verification, rule,
                                certificate=certificate, tenant_id=tenant_id)
        binding = binding_digest(tool, agent_id, tenant_id, request, certificate)

        if rule.requires_human_approval:
            if approval is None:
                return self._decide(tool, agent_id, (HUMAN_APPROVAL_REQUIRED,),
                                    verification, rule, certificate=certificate, tenant_id=tenant_id)
            if (approval.approver_id not in self.policy.approvers
                    or approval.approver_id == agent_id
                    or approval.certificate_digest != certificate.digest()
                    or (approval.binding is not None and approval.binding != binding)):
                return self._decide(tool, agent_id, (APPROVAL_INVALID,),
                                    verification, rule, certificate=certificate, tenant_id=tenant_id)

        grant_id = grant.grant_id if isinstance(grant, Grant) else grant
        if rule.requires_grant or grant_id is not None:
            if grant_id is None:
                return self._decide(tool, agent_id, (GRANT_REQUIRED,), verification, rule,
                                    certificate=certificate, tenant_id=tenant_id, binding=binding)
            problem = self._check_grant(grant_id, tool, agent_id, binding)
            if problem:
                return self._decide(tool, agent_id, (problem,), verification, rule,
                                    certificate=certificate, tenant_id=tenant_id,
                                    grant_id=grant_id, binding=binding)
        return self._decide(tool, agent_id, (ALLOWED,), verification, rule,
                            allowed=True, certificate=certificate, tenant_id=tenant_id,
                            grant_id=grant_id, binding=binding)

    # --- origin-bound authority and exact-action grants --------------------

    def _authority(self, certificate: EvidenceCertificate, rule: ToolRule) -> str | None:
        from . import authority

        if rule.min_authority == authority.UNTRUSTED:
            return None
        for item in certificate.evidence:
            try:
                found = authority.of(self.fabric, item.memory_id)
            except Exception:
                return STATE_UNAVAILABLE
            if found.kind == "instruction":
                return INSTRUCTION_EVIDENCE
            if not found.at_least(rule.min_authority):
                return AUTHORITY_INSUFFICIENT
        return None

    def issue_grant(self, tool: str, agent_id: str, issuer: str, *,
                    certificate: EvidenceCertificate | None = None,
                    request: ActionRequest | None = None,
                    tenant_id: str | None = None, ttl_s: float = 60.0) -> Grant:
        """A grant for one exact action, valid for `ttl_s` and consumed by its first use.

        The issuer is the host or a human; it must not be the agent.
        """
        from .ids import new_ulid

        if issuer == agent_id:
            raise ValueError("an agent cannot grant itself an action")
        if not 0 < ttl_s <= MAX_GRANT_TTL_S:
            raise ValueError(f"ttl_s must be in (0, {MAX_GRANT_TTL_S}]")
        if tool not in self.policy.grants.get(agent_id, frozenset()):
            raise ValueError(f"{agent_id} is not granted {tool}")
        binding = binding_digest(tool, agent_id, tenant_id, request, certificate)
        grant = Grant("gr_" + new_ulid(), tool, agent_id, binding,
                      self.fabric.now() + int(ttl_s * 1000))
        self.fabric._emit(ev.grant_issued(ts=self.fabric.now(), grant_id=grant.grant_id,
                                          tool=tool, agent_id=agent_id, binding=binding,
                                          expires_ms=grant.expires_ms, issuer=issuer))
        return grant

    def revoke_grant(self, grant_id: str, issuer: str) -> None:
        self.fabric._emit(ev.grant_issued(ts=self.fabric.now(), grant_id=grant_id, tool="",
                                          agent_id="", binding="", expires_ms=0,
                                          issuer=issuer, revoked=True))

    def _check_grant(self, grant_id: str, tool: str, agent_id: str, binding: str) -> str | None:
        issued = None
        revoked = False
        for event in self.fabric.log.read_types([ev.EventType.GRANT_ISSUED]):
            if event.payload.get("grant_id") != grant_id:
                continue
            if event.payload.get("revoked"):
                revoked = True
            elif issued is None:
                issued = event.payload
        if issued is None:
            return GRANT_UNKNOWN
        if revoked:
            return GRANT_REVOKED
        if self.fabric.now() >= int(issued["expires_ms"]):
            return GRANT_EXPIRED
        if (issued["tool"], issued["agent"], issued["binding"]) != (tool, agent_id, binding):
            return GRANT_MISMATCH
        for event in self.fabric.log.read_types([ev.EventType.ACTION_GATED]):
            if event.payload.get("grant_id") == grant_id and event.payload.get("allowed"):
                return GRANT_REPLAYED
        return None

    def execute(
        self,
        tool: str,
        agent_id: str,
        run: Callable[[str], Any],
        certificate: EvidenceCertificate | Mapping[str, Any] | None = None,
        *,
        key: str,
        lease_s: float = 2.0,
        tenant_id: str | None = None,
        approval: Approval | None = None,
        session: Any = None,
        retry: bool = False,
        request: ActionRequest | None = None,
        grant: Grant | str | None = None,
    ) -> ActionExecution:
        """Authorize and run `run(key)` with no window between them (module docstring).

        `run` is the tool's side effect. It receives `key` so it can
        deduplicate. It must not call this store.
        """
        if not 0 < lease_s < MAX_LEASE_S:
            raise ValueError(f"lease_s must be in (0, {MAX_LEASE_S}); writers in other "
                             "processes give up after the store's busy timeout")
        prior = self._last_execution(key)
        if prior is not None:
            if prior["outcome"] == EXECUTED:
                return ActionExecution(ALREADY_EXECUTED, None, key)
            if not retry:
                return ActionExecution(REFUSED, None, key, error=(
                    f"{RETRY_REQUIRED}: the last attempt {prior['outcome']} with an unknown "
                    "effect; pass retry=True to re-verify and run again"))
        if isinstance(certificate, Mapping):
            try:
                certificate = EvidenceCertificate.from_json(certificate)
            except CertificateError:
                pass  # authorize reports it
        fabric = self.fabric
        with fabric.lock, fabric._transaction():
            decision = self.authorize(tool, agent_id, certificate, tenant_id=tenant_id,
                                      approval=approval, session=session,
                                      request=request, grant=grant)
            if not decision.allowed:
                return ActionExecution(REFUSED, decision, key)
            box: dict[str, Any] = {}

            def work() -> None:
                try:
                    box["result"] = run(key)
                except BaseException as exc:  # noqa: BLE001 - reported, not swallowed
                    box["error"] = f"{type(exc).__name__}: {exc}"

            started = time.monotonic()
            worker = threading.Thread(target=work, name=f"action-{key}", daemon=True)
            worker.start()
            worker.join(lease_s)
            elapsed_ms = int((time.monotonic() - started) * 1000)
            if worker.is_alive():
                outcome, fenced = TIMED_OUT, False
            elif "error" in box:
                outcome, fenced = FAILED, True
            else:
                outcome, fenced = EXECUTED, True
            verification = decision.verification
            evidence = ([[e.memory_id, e.version] for e in certificate.evidence]
                        if isinstance(certificate, EvidenceCertificate) else [])
            fabric._emit(ev.action_executed(
                ts=fabric.now(), agent_id=decision.agent_id, key=key, tool=tool,
                outcome=outcome, fenced=fenced,
                watermark=verification.verified_at_watermark if verification else None,
                lease_ms=int(lease_s * 1000), elapsed_ms=elapsed_ms, evidence=evidence,
                tenant_id=tenant_id))
        return ActionExecution(outcome, decision, key, result=box.get("result"),
                               error=box.get("error"), fenced=fenced)

    def _last_execution(self, key: str) -> Mapping[str, Any] | None:
        last = None
        for event in self.fabric.log.read_types([ev.EventType.ACTION_EXECUTED]):
            if event.payload.get("key") == key:
                last = event.payload
        return last

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
        tenant_id: str | None = None,
        grant_id: str | None = None,
        binding: str | None = None,
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
                    tenant_id=tenant_id,
                    required_checks=list(dict.fromkeys(
                        [*(certificate.required_checks if certificate else ()),
                         *(rule.required_checks if rule else ())])),
                    min_independent_sources=max(
                        certificate.min_independent_sources if certificate else 0,
                        rule.min_independent_sources if rule else 0),
                    grant_id=grant_id, binding=binding,
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


def unfenced_changes(fabric: Any) -> list[dict[str, Any]]:
    """Changes to an action's evidence that landed after its fence was released.

    For every `timed_out` execution: lifecycle changes to any memory it rested
    on, recorded after the execution. Each is a withdrawal the tool may have
    acted against. That is the bounded remainder of S14, made visible rather
    than closed. A fenced execution cannot appear here, because nothing could
    commit inside its window.
    """
    out: list[dict[str, Any]] = []
    pending: list[tuple[int, Mapping[str, Any]]] = []
    for event in fabric.log.read_types([ev.EventType.ACTION_EXECUTED,
                                        ev.EventType.LIFECYCLE_CHANGED]):
        if event.type == ev.EventType.ACTION_EXECUTED:
            if not event.payload.get("fenced", True):
                pending.append((event.seq or 0, event.payload))
            continue
        memory_id = event.payload.get("memory_id")
        for seq, execution in pending:
            if any(e[0] == memory_id for e in execution.get("evidence", [])):
                out.append({"key": execution["key"], "tool": execution["tool"],
                            "memory_id": memory_id, "change_seq": event.seq,
                            "execution_seq": seq})
    return out
