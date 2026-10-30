"""Who can reach a memory, and who already has.

The question an operator asks first about any memory: *why does this agent
know this, and who else does?* Three different facts answer it, and the
console keeps them apart, because conflating them is how a governance view
ends up reassuring rather than accurate:

- **may read**: what scope and tenancy allow now. Private is the agent that
  wrote it; team and federated are every agent in its tenant
  (`model.visible_to`). A memory that retrieval refuses (a candidate, a
  quarantined or deprecated one) can be read by nobody, whatever its scope.
- **has seen**: agents it was actually put in front of, from the exposure log,
  and agents who asked and were refused, from the denial log. History, not
  permission: an agent that saw a memory before it was withdrawn has still
  seen it.
- **other stores**: stores it was sent to, from `MemoryShared`, with the id
  the copy has there. A retraction follows these.
"""

from __future__ import annotations

__stability__ = "beta"

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from .events import EventType
from .model import EXPOSABLE_STATES, BLOCKED_STATES, Scope

if TYPE_CHECKING:  # pragma: no cover
    from .fabric import Amberlog


@dataclass
class Reach:
    memory_id: str
    tenant_id: str
    scope: str
    may_read: str
    readable_now: bool
    why_not: str = ""
    seen_by: dict[str, int] = field(default_factory=dict)
    refused: dict[str, int] = field(default_factory=dict)
    stores: list[dict[str, Any]] = field(default_factory=list)

    def to_json(self) -> dict[str, Any]:
        return dict(self.__dict__)


def reach(fabric: "Amberlog", memory_id: str) -> Reach:
    memory = fabric.state.memories[memory_id]
    state = memory.lifecycle_state
    if memory.scope is Scope.PRIVATE:
        readers = sorted({agent for (tenant, name), c in fabric.state.collections.items()
                          if tenant == memory.tenant_id and memory_id in c.members
                          for agent, perms in c.grants.items() if "read" in perms}
                         - {memory.provenance.created_by})
        may_read = f"only {memory.provenance.created_by}, who wrote it"
        if readers:
            may_read = (f"{memory.provenance.created_by}, who wrote it, and through a "
                        f"collection: {', '.join(readers)}")
    else:
        may_read = f"every agent in tenant {memory.tenant_id}"
    if memory.scope is Scope.FEDERATED:
        may_read += "; it may also be sent to other stores"
    readable = state in EXPOSABLE_STATES and state not in BLOCKED_STATES
    why_not = "" if readable else f"retrieval refuses {state.value} memories"

    seen: dict[str, int] = {}
    refused: dict[str, int] = {}
    stores: list[dict[str, Any]] = []
    types = [EventType.EXPOSURE_DECIDED, EventType.ACCESS_DENIED, EventType.MEMORY_SHARED]
    for event in fabric.log.read_types(types):
        payload = event.payload
        if payload.get("memory_id") != memory_id:
            continue
        agent = event.agent_id or "unknown"
        if event.type == EventType.EXPOSURE_DECIDED and payload.get("exposed"):
            seen[agent] = seen.get(agent, 0) + 1
        elif event.type == EventType.ACCESS_DENIED:
            refused[agent] = refused.get(agent, 0) + 1
        elif event.type == EventType.MEMORY_SHARED:
            stores.append({"store_id": payload.get("recipient_store_id"),
                           "imported_memory_id": payload.get("imported_memory_id"),
                           "version": payload.get("version"), "sent_by": agent})
    return Reach(memory_id=memory_id, tenant_id=memory.tenant_id, scope=memory.scope.value,
                 may_read=may_read, readable_now=readable, why_not=why_not,
                 seen_by=dict(sorted(seen.items())), refused=dict(sorted(refused.items())),
                 stores=stores)
