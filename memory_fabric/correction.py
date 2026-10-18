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
  it, in one transaction (the protocol's invariant 3).
- `status`: per store, what each recipient has acknowledged.
"""

from __future__ import annotations

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

    def to_json(self) -> dict[str, Any]:
        return dict(self.__dict__)


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
    return result


def apply(fabric: "MemoryFabric", memory_id: str, reason: str, actor: str,
          basis: str = WithdrawalBasis.CONTRADICTED.value) -> dict[str, Any]:
    """Quarantine and owe the retraction to every store that received the memory."""
    if not actor or actor == "operator":
        raise ValueError("name who is correcting this: the decision is audited")
    recipients = sorted({s["store_id"] for s in _stores(fabric, memory_id) if s["store_id"]})
    retraction = fabric.request_retraction(memory_id, reason=reason, recipients=recipients,
                                           actor=actor, basis=basis)
    return {"memory_id": memory_id, "retraction_id": retraction.retraction_id,
            "owed_to": recipients}


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
