"""Active memory auditing, observation only (plan R6, Task 10).

The auditor decides where to spend extra verification. It never decides
anything else. It reads the event log and the outbox and writes nothing:
no quarantine, no forgetting, no event. A finding is a recommendation for
an operator. The enforcement layer, the certificate verifier and the action
gate do not consult it, so a risk score cannot loosen a mandatory check or
tighten one. `tests/test_auditor.py` pins both properties.

Triggers, each a cheap signal over new log entries:

- `high_impact_action`: a gated action that required two or more
  independent sources. Re-checked: is its evidence still good now?
- `source_withdrawn`: a memory quarantined on a finding about its content.
  Re-checked: which actions used it, and which conclusions drawn from it are
  still active?
- `contradiction`: a hypothesis set was opened. Re-checked: is it still
  unresolved?
- `write_burst`: an agent writing far faster than its peers in a window.
  Re-checked: how many of its writes the screens quarantined, and how many
  are still active.
- `propagation_failure`: an outbox delivery gave up. Re-checked: still failed?

Every trigger carries a deterministic risk score, used only to order audits
under a budget (`experiments/p10_audit.py` compares periodic,
event-triggered and risk-budgeted policies).
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from . import events as ev
from .certificates import CertificateVerifier, EvidenceCertificate, EvidenceRef
from .model import BLOCKED_STATES, LifecycleState

HIGH_IMPACT = "high_impact_action"
SOURCE_WITHDRAWN = "source_withdrawn"
CONTRADICTION = "contradiction"
WRITE_BURST = "write_burst"
PROPAGATION_FAILURE = "propagation_failure"
SAMPLE = "sample"  # a periodic audit of a subject chosen without a trigger

RISK = {PROPAGATION_FAILURE: 0.9, SOURCE_WITHDRAWN: 0.8, HIGH_IMPACT: 0.6,
        WRITE_BURST: 0.5, CONTRADICTION: 0.4, SAMPLE: 0.1}
STRONG_BASES = frozenset({"contradicted", "sensitive_data", "contrastive_harm"})


@dataclass(frozen=True)
class Trigger:
    kind: str
    subject: str
    seq: int
    risk: float
    detail: str = ""


@dataclass(frozen=True)
class AuditResult:
    trigger: Trigger
    finding: bool
    detail: str
    events_read: int
    related: tuple[str, ...] = field(default_factory=tuple)


class Auditor:
    """Read-only. Holds a fabric and never calls a mutating method on it."""

    def __init__(self, fabric: Any, burst_window: int = 40, burst_factor: float = 3.0,
                 burst_min: int = 8) -> None:
        self.fabric = fabric
        self.burst_window = burst_window
        self.burst_factor = burst_factor
        self.burst_min = burst_min

    # --- triggers --------------------------------------------------------

    def scan(self, since_seq: int = 0) -> list[Trigger]:
        # Reading only, but reading another process's writes needs a refresh.
        if callable(getattr(self.fabric, "refresh", None)):
            self.fabric.refresh()
        log = self.fabric.log
        events = [e for e in log.read(since_seq=since_seq)]
        out: list[Trigger] = []
        writes: list[Any] = []
        for e in events:
            p = e.payload
            if e.type == ev.EventType.ACTION_GATED and p.get("allowed") \
                    and (p.get("min_independent_sources") or 0) >= 2:
                out.append(Trigger(HIGH_IMPACT, str(e.seq), e.seq, RISK[HIGH_IMPACT],
                                   str(p.get("tool"))))
            elif e.type == ev.EventType.LIFECYCLE_CHANGED and p.get("to") == "quarantined" \
                    and p.get("basis") in STRONG_BASES:
                out.append(Trigger(SOURCE_WITHDRAWN, str(p.get("memory_id")), e.seq,
                                   RISK[SOURCE_WITHDRAWN], str(p.get("basis"))))
            elif e.type == ev.EventType.CONFLICT_DETECTED:
                out.append(Trigger(CONTRADICTION, str(p.get("hypothesis_set") or p.get("set_id")
                                                      or ",".join(p.get("memory_ids") or [])),
                                   e.seq, RISK[CONTRADICTION]))
            elif e.type == ev.EventType.MEMORY_CREATED:
                writes.append(e)
        out.extend(self._bursts(writes))
        for row in self._failed_deliveries():
            out.append(Trigger(PROPAGATION_FAILURE, f"{row.retraction_id}->{row.recipient}",
                               log.head_seq, RISK[PROPAGATION_FAILURE], row.last_error or ""))
        return sorted(out, key=lambda t: t.seq)

    def _bursts(self, writes: list[Any]) -> list[Trigger]:
        out: list[Trigger] = []
        flagged: set[str] = set()
        for i in range(len(writes)):
            window = writes[max(0, i - self.burst_window + 1): i + 1]
            counts = Counter(e.agent_id for e in window)
            agent, n = counts.most_common(1)[0]
            others = [c for a, c in counts.items() if a != agent] or [0]
            typical = sorted(others)[len(others) // 2]
            if agent not in flagged and n >= self.burst_min \
                    and n >= self.burst_factor * max(typical, 1):
                flagged.add(agent)
                out.append(Trigger(WRITE_BURST, str(agent), writes[i].seq,
                                   RISK[WRITE_BURST], f"{n} of the last {len(window)} writes"))
        return out

    def _failed_deliveries(self) -> list[Any]:
        outbox = getattr(self.fabric, "outbox", None)
        if outbox is None:
            return []
        # Read directly: a failed delivery is settled, so `pending()` omits it.
        rows = outbox._conn.execute(
            "SELECT * FROM outbox WHERE state = 'failed' ORDER BY id").fetchall()
        return [outbox._row(r) for r in rows]

    # --- audits ----------------------------------------------------------

    def audit(self, trigger: Trigger) -> AuditResult:
        handler = {
            HIGH_IMPACT: self._audit_action, SOURCE_WITHDRAWN: self._audit_withdrawal,
            CONTRADICTION: self._audit_contradiction, WRITE_BURST: self._audit_writer,
            PROPAGATION_FAILURE: self._audit_delivery, SAMPLE: self._audit_sample,
        }[trigger.kind]
        return handler(trigger)

    def _action_event(self, seq: int) -> Any:
        return next((e for e in self.fabric.log.read_types([ev.EventType.ACTION_GATED])
                     if e.seq == seq), None)

    def _audit_action(self, t: Trigger) -> AuditResult:
        event = self._action_event(int(t.subject))
        if event is None:
            return AuditResult(t, False, "action not found", 1)
        p = event.payload
        cert = EvidenceCertificate(
            claim_id=str(p.get("claim_id") or "audit"), agent_id=str(event.agent_id),
            store_id=self.fabric.store_id, tenant_id=p.get("tenant_id"),
            evidence=tuple(EvidenceRef(m, int(v)) for m, v in p.get("evidence") or []),
            dependencies=(), policy_id=getattr(self.fabric.policy, "id", ""),
            snapshot_watermark=int(p.get("watermark") or 0), issued_at_ms=0,
            required_checks=tuple(c for c in p.get("required_checks") or ()
                                  if c != "dependencies_current") or ("evidence_current",),
            min_independent_sources=int(p.get("min_independent_sources") or 1))
        result = CertificateVerifier(self.fabric).verify(
            cert, agent_id=str(event.agent_id), tenant_id=p.get("tenant_id"))
        return AuditResult(t, not result.ok,
                           "evidence no longer verifies: " + ",".join(result.reason_codes)
                           if not result.ok else "evidence still verifies",
                           1 + len(cert.evidence),
                           tuple(r.memory_id for r in cert.evidence))

    def _audit_withdrawal(self, t: Trigger) -> AuditResult:
        withdrawn = t.subject
        used_by = [e for e in self.fabric.log.read_types([ev.EventType.ACTION_GATED])
                   if e.payload.get("allowed")
                   and any(m == withdrawn for m, _ in e.payload.get("evidence") or [])]
        state = self.fabric.state
        active_children = [c for c in sorted(state.children.get(withdrawn, ()))
                           if state.memories[c].lifecycle_state is LifecycleState.ACTIVE]
        memory = state.memories.get(withdrawn)
        writer = memory.provenance.created_by if memory else ""
        siblings = [m.id for m in state.memories.values()
                    if writer and m.provenance.created_by == writer
                    and m.lifecycle_state is LifecycleState.ACTIVE]
        finding = bool(used_by) or bool(active_children)
        return AuditResult(
            t, finding,
            f"{len(used_by)} allowed action(s) used it; {len(active_children)} "
            f"derived memory(ies) still active; writer {writer} has "
            f"{len(siblings)} other active write(s) to review",
            1 + len(used_by),
            tuple(str(e.seq) for e in used_by) + tuple(active_children)
            + ((writer,) if writer else ()))

    def _audit_contradiction(self, t: Trigger) -> AuditResult:
        open_sets = [s for s in self.fabric.state.hypothesis_sets.values() if not s.resolved]
        relevant = [s for s in open_sets if s.id == t.subject
                    or ",".join(sorted(s.memory_ids)) == ",".join(sorted(t.subject.split(",")))]
        return AuditResult(t, bool(relevant),
                           "still unresolved" if relevant else "resolved", 1,
                           tuple(s.id for s in relevant))

    def _audit_writer(self, t: Trigger) -> AuditResult:
        mine = [m for m in self.fabric.state.memories.values()
                if m.provenance.created_by == t.subject]
        screened = sum(1 for m in mine if m.lifecycle_state in BLOCKED_STATES)
        withdrawn_basis = [m for m in mine if self.fabric.state.withdrawal_basis.get(m.id)
                           in STRONG_BASES]
        finding = bool(withdrawn_basis)
        return AuditResult(t, finding,
                           f"{len(mine)} writes, {screened} withdrawn, "
                           f"{len(withdrawn_basis)} on a finding about content",
                           len(mine), tuple(m.id for m in withdrawn_basis))

    def _audit_delivery(self, t: Trigger) -> AuditResult:
        still = any(f"{r.retraction_id}->{r.recipient}" == t.subject
                    for r in self._failed_deliveries())
        return AuditResult(t, still, "delivery still failed" if still else "recovered", 1)

    def _audit_sample(self, t: Trigger) -> AuditResult:
        """A periodic check of one subject (an agent id or an action seq)."""
        if t.subject.isdigit():
            return self._audit_action(Trigger(HIGH_IMPACT, t.subject, t.seq, t.risk))
        return self._audit_writer(Trigger(WRITE_BURST, t.subject, t.seq, t.risk))
