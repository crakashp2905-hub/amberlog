"""Evidence-backed, versioned mental models (plan R9, Task 8).

A mental model is a summary that an agent or team keeps about a subject, such
as "what we know about the harbour cranes". The plan's requirement is not that
summaries exist; other systems have them. It is that a summary knows exactly
what it rests on, becomes stale the moment any of that changes, is never
presented as current while stale, and is refreshed without redoing every other
model.

**Built on what exists, with no new event type.** A model *is* a derived
memory: `derive` records each piece of evidence and its version as a REQUIRED
premise, so truth maintenance already contests the model when a premise is
withdrawn or revised. A contested memory fails the enforcer at high risk, so a
stale model cannot satisfy a protected action's certificate, and that falls
out of the existing layers rather than a new rule. This module adds what
derivation alone lacks:

- `status` names *which* evidence changed and how;
- `refresh_queue` is coalesced, so many changes to one model's evidence produce
  one refresh, and models whose evidence did not change are never queued;
- `refresh` is idempotent: a fresh model is not rewritten, and a refreshed one
  supersedes its predecessor (deprecated, not deleted, so history stays).

The model's identity and watermark live in the derived memory's context, so
the registry is a projection of the log and survives a restart.
"""

from __future__ import annotations

__stability__ = "experimental"

from dataclasses import dataclass
from typing import Any, Callable, Sequence

from .enforcement import RiskLevel
from .justification import JustificationKind, justification_context
from .model import BLOCKED_STATES, LifecycleState

MODEL_KEY = "mental_model"
WATERMARK_KEY = "model_watermark"

FRESH = "fresh"
STALE = "stale"
MISSING = "missing"
INSUFFICIENT = "insufficient_evidence"
PENDING_REVIEW = "pending_review"
"""Evidence unchanged, model written but not yet validated. Not current, and
not queued: refreshing it again would only write another unreviewed copy."""


@dataclass(frozen=True)
class EvidenceChange:
    memory_id: str
    recorded_version: int
    reason: str  # withdrawn | revised | missing | not_usable


@dataclass(frozen=True)
class ModelStatus:
    model_id: str
    state: str
    memory_id: str | None = None
    watermark: int | None = None
    evidence: tuple[tuple[str, int], ...] = ()
    changes: tuple[EvidenceChange, ...] = ()

    @property
    def fresh(self) -> bool:
        return self.state == FRESH


@dataclass(frozen=True)
class RefreshResult:
    model_id: str
    refreshed: bool
    state: str
    memory_id: str | None
    superseded: str | None = None


Summarizer = Callable[[Sequence[Any]], str]


class MentalModels:
    def __init__(self, fabric: Any) -> None:
        self.fabric = fabric

    # --- registry (a projection of memories) -----------------------------

    def _versions(self, model_id: str) -> list[Any]:
        return sorted(
            (m for m in self.fabric.state.memories.values()
             if m.context.get(MODEL_KEY) == model_id),
            key=lambda m: (m.context.get(WATERMARK_KEY, 0), m.created_at))

    def current(self, model_id: str) -> Any | None:
        live = [m for m in self._versions(model_id)
                if m.lifecycle_state is not LifecycleState.DEPRECATED
                and m.lifecycle_state is not LifecycleState.DELETED]
        return live[-1] if live else None

    def model_ids(self) -> list[str]:
        return sorted({m.context[MODEL_KEY] for m in self.fabric.state.memories.values()
                       if MODEL_KEY in m.context})

    def affected_by(self, memory_id: str) -> list[str]:
        """Models whose current version rests on `memory_id`."""
        out = []
        for model_id in self.model_ids():
            memory = self.current(model_id)
            if memory is not None and any(p == memory_id for p, _ in memory.provenance.parents):
                out.append(model_id)
        return out

    # --- writing ---------------------------------------------------------

    def define(self, model_id: str, agent_id: str, evidence_ids: Sequence[str],
               content: str, tenant_id: str | None = None) -> str:
        """Write a model resting on `evidence_ids`. Every piece is REQUIRED: a
        summary that includes something is wrong once that thing is."""
        if not evidence_ids:
            raise ValueError("a mental model needs evidence")
        context = {
            MODEL_KEY: model_id,
            WATERMARK_KEY: self.fabric.log.head_seq,
            **justification_context([(e, JustificationKind.REQUIRED) for e in evidence_ids]),
        }
        return self.fabric.derive(agent_id, content, parents=list(evidence_ids),
                                  context=context, tenant_id=tenant_id)

    # --- status ----------------------------------------------------------

    def status(self, model_id: str) -> ModelStatus:
        memory = self.current(model_id)
        if memory is None:
            return ModelStatus(model_id, MISSING)
        changes: list[EvidenceChange] = []
        for pid, version in memory.provenance.parents:
            evidence = self.fabric.state.memories.get(pid)
            if evidence is None:
                changes.append(EvidenceChange(pid, version, "missing"))
            elif evidence.lifecycle_state in BLOCKED_STATES:
                changes.append(EvidenceChange(pid, version, "withdrawn"))
            elif evidence.version != version:
                changes.append(EvidenceChange(pid, version, "revised"))
            elif evidence.lifecycle_state is not LifecycleState.ACTIVE:
                changes.append(EvidenceChange(pid, version, "not_usable"))
        if changes or memory.lifecycle_state is not LifecycleState.ACTIVE:
            state = (PENDING_REVIEW if not changes
                     and memory.lifecycle_state is LifecycleState.CANDIDATE else STALE)
        else:
            state = FRESH
        return ModelStatus(
            model_id, state, memory.id,
            memory.context.get(WATERMARK_KEY), tuple(memory.provenance.parents),
            tuple(changes))

    def refresh_queue(self) -> list[str]:
        """Each stale model once, however many of its inputs changed."""
        return [m for m in self.model_ids() if self.status(m).state == STALE]

    # --- refreshing ------------------------------------------------------

    def refresh(self, model_id: str, summarize: Summarizer, agent_id: str) -> RefreshResult:
        status = self.status(model_id)
        if status.state in (FRESH, PENDING_REVIEW):
            return RefreshResult(model_id, False, status.state, status.memory_id)
        if status.state == MISSING:
            return RefreshResult(model_id, False, MISSING, None)
        old = self.fabric.state.memories[status.memory_id]
        usable = []
        for pid, _ in old.provenance.parents:
            decision = self.fabric.enforcer.check(pid, risk=RiskLevel.HIGH,
                                                  tenant_id=old.tenant_id)
            if decision.usable:
                usable.append(self.fabric.state.memories[pid])
        if not usable:
            # Nothing left to summarise. The old model stays as it is
            # (contested) rather than being rewritten from nothing.
            return RefreshResult(model_id, False, INSUFFICIENT, status.memory_id)
        new_id = self.define(model_id, agent_id, [m.id for m in usable],
                             summarize(usable), tenant_id=old.tenant_id)
        self.fabric.forget(old.id, reason=f"superseded by refresh of model {model_id}",
                           actor=agent_id)
        return RefreshResult(model_id, True, self.status(model_id).state, new_id, old.id)

    def refresh_all(self, summarize: Summarizer, agent_id: str) -> list[RefreshResult]:
        return [self.refresh(m, summarize, agent_id) for m in self.refresh_queue()]
