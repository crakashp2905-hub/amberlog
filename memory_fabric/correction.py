"""Safe correction: preview what a withdrawal touches, apply it, watch it land.

Withdrawing a memory is not one change. Conclusions built on it lose their
support unless something independent still holds them up; copies of it fall
with it; stores it was sent to are owed a retraction. An operator should see
all of that *before* deciding, and the preview must be what actually happens,
so it does not reimplement the rules: it uses `incident.supported`, which
mirrors `JustificationGraph.recompute` rule for rule and was measured against
live withdrawal in P9. `tests/test_correction.py` checks the preview against
the outcome.

- `preview`: what withdrawing a memory would contest, what would survive on
  independent support, which copies fall with it, and which stores are owed
  a retraction.
- `apply`: quarantine it and owe the retraction to every store that received
  it, in one transaction (the protocol's invariant 3). Given the preview's
  `digest`, it first recomputes the preview **inside the same transaction**
  and refuses with `StalePreview` if anything it showed has changed: a
  version, a descendant's state, a new copy or recipient. An operator never
  applies a blast radius they did not see.
- `status`: per store, what each recipient has acknowledged.
"""

from __future__ import annotations

__stability__ = "beta"

import hashlib
import json
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from .events import EventType
from .incident import _copy_component, supported
from .model import LifecycleState, WithdrawalBasis

if TYPE_CHECKING:  # pragma: no cover
    from .fabric import MemoryFabric


@dataclass
class CorrectionPreview:
    memory_id: str
    would_contest: list[str] = field(default_factory=list)
    """Active descendants and copies that lose all support."""
    would_survive: list[str] = field(default_factory=list)
    """Active descendants still held up by independent support."""
    copies: list[str] = field(default_factory=list)
    stores: list[dict[str, Any]] = field(default_factory=list)
    """Stores holding a copy: each is owed a retraction."""
    digest: str = ""
    """What this preview was computed from; `apply(preview_digest=...)` checks it."""

    def to_json(self) -> dict[str, Any]:
        return dict(self.__dict__)


class StalePreview(Exception):
    """The store changed after the preview was shown. Preview again; nothing was applied."""

    code = "STALE_PREVIEW"


def _digest(state: Any, result: CorrectionPreview) -> str:
    touched = sorted({result.memory_id, *result.would_contest, *result.would_survive,
                      *result.copies, *_descendants(state, result.memory_id)})
    basis = {"memories": [[m, state.memories[m].version, state.memories[m].lifecycle_state.value]
                          for m in touched if m in state.memories],
             "contest": result.would_contest, "survive": result.would_survive,
             "copies": result.copies,
             "stores": sorted((s["store_id"] or "", s["imported_memory_id"] or "")
                              for s in result.stores)}
    return hashlib.sha256(json.dumps(basis, sort_keys=True).encode()).hexdigest()


def _descendants(state: Any, memory_id: str) -> set[str]:
    seen: set[str] = set()
    frontier = [memory_id]
    while frontier:
        for child in state.children.get(frontier.pop(), ()):
            if child not in seen:
                seen.add(child)
                frontier.append(child)
    return seen


def _stores(fabric: "MemoryFabric", memory_id: str) -> list[dict[str, Any]]:
    out = []
    for event in fabric.log.read_types([EventType.MEMORY_SHARED]):
        if event.payload.get("memory_id") == memory_id:
            out.append({"store_id": event.payload.get("recipient_store_id"),
                        "imported_memory_id": event.payload.get("imported_memory_id")})
    return out


def preview(fabric: "MemoryFabric", memory_id: str) -> CorrectionPreview:
    state = fabric.state
    if memory_id not in state.memories:
        raise KeyError(memory_id)
    lost = frozenset({memory_id})
    copies = sorted(_copy_component(state, memory_id) - {memory_id})
    result = CorrectionPreview(memory_id, copies=copies, stores=_stores(fabric, memory_id))
    memo: dict[str, bool] = {}
    for other in sorted(_descendants(state, memory_id) | set(copies)):
        if state.memories[other].lifecycle_state is not LifecycleState.ACTIVE:
            continue
        if supported(state, other, lost, memo):
            result.would_survive.append(other)
        else:
            result.would_contest.append(other)
    result.digest = _digest(state, result)
    return result


def apply(fabric: "MemoryFabric", memory_id: str, reason: str, actor: str,
          basis: str = WithdrawalBasis.CONTRADICTED.value,
          preview_digest: str | None = None) -> dict[str, Any]:
    """Quarantine and owe the retraction to every store that received the memory.

    With `preview_digest`, refuses with `StalePreview` unless the preview
    computed now, under the write lock, is the one that was shown.
    """
    if not actor or actor == "operator":
        raise ValueError("name who is correcting this: the decision is audited")
    with fabric._transaction():
        if preview_digest is not None:
            current = preview(fabric, memory_id)
            # A prefix is accepted, so the CLI can print a short one.
            if len(preview_digest) < 12 or not current.digest.startswith(preview_digest):
                raise StalePreview(f"{memory_id} changed since the preview: preview again")
        recipients = sorted({s["store_id"] for s in _stores(fabric, memory_id) if s["store_id"]})
        retraction = fabric.request_retraction(memory_id, reason=reason, recipients=recipients,
                                               actor=actor, basis=basis)
    return {"memory_id": memory_id, "retraction_id": retraction.retraction_id,
            "owed_to": recipients, "preview_checked": preview_digest is not None}


def status(fabric: "MemoryFabric", memory_id: str) -> list[dict[str, Any]]:
    """Each recipient's latest acknowledgement, per retraction of this memory."""
    out = []
    for event in fabric.log.read_types([EventType.RETRACTION_REQUESTED]):
        payload = event.payload
        if payload.get("origin_memory_id") != memory_id:
            continue
        acks = fabric.outbox.acknowledgements(payload["retraction_id"])
        for recipient in payload.get("recipients") or ():
            ack = acks.get(recipient)
            out.append({"retraction_id": payload["retraction_id"], "store_id": recipient,
                        "state": ack.state.value if ack else "queued",
                        "detail": ack.detail if ack else ""})
    return out
