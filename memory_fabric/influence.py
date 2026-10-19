"""The influence graph: typed edges from a memory to what it touched, rebuilt from the log.

Every edge is a projection of an event already in the log, so the graph can
be rebuilt at any point (AGENTS.md principle 3) and adds no schema.

| edge | from → to | recorded by |
|---|---|---|
| `derived_from` | conclusion → premise | provenance parents (method other than consolidated) |
| `summarized_from` | summary → source | provenance parents, method `consolidated` |
| `copied_from` | copy → original | copy recognition (`copy_of`) |
| `imported_from` | import → `<store>/<memory>` | `context.federation` |
| `exposed_to` | memory → `agent:<id>` / `episode:<id>` | `ExposureDecided` (exposed) |
| `relied_on` | `episode:<id>` → memory | `MemoryCited` |
| `authorized` | memory → `action:<seq>` | `ActionGated` allowed, `ActionExecuted` |
| `invalidated_by` | memory → `event:<seq>` | `LifecycleChanged` to a withdrawn state |

`impact` separates three sets an incident must not collapse:

- **potentially contaminated**: everything downstream through lineage, copies
  and imports, and every agent it was shown to. What *might* carry it.
- **actually retrieved**: exposures of the memory or of anything downstream.
- **confirmed use**: citations and actions that rested on any of them.
"""

from __future__ import annotations

__stability__ = "beta"

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Iterable

from .events import EventType

if TYPE_CHECKING:  # pragma: no cover
    from .fabric import MemoryFabric

EDGE_TYPES = ("derived_from", "summarized_from", "copied_from", "imported_from",
              "exposed_to", "relied_on", "authorized", "invalidated_by")


@dataclass(frozen=True)
class Edge:
    type: str
    source: str
    target: str
    seq: int | None = None


def edges(fabric: "MemoryFabric") -> list[Edge]:
    """Every typed edge in the store."""
    from .model import ProvenanceMethod, WITHDRAWN_STATES

    out: list[Edge] = []
    withdrawn = {s.value for s in WITHDRAWN_STATES}
    for memory in fabric.state.memories.values():
        kind = ("summarized_from" if memory.provenance.method is ProvenanceMethod.CONSOLIDATED
                else "derived_from")
        for parent, _ in memory.provenance.parents:
            out.append(Edge(kind, memory.id, parent))
        fed = (memory.context or {}).get("federation")
        if isinstance(fed, dict):
            out.append(Edge("imported_from", memory.id, f"{fed.get('store')}/{fed.get('memory_id')}"))
    for copy, original in fabric.state.copy_of.items():
        out.append(Edge("copied_from", copy, original))
    for event in fabric.log.read_types([EventType.EXPOSURE_DECIDED, EventType.MEMORY_CITED,
                                        EventType.ACTION_GATED, EventType.ACTION_EXECUTED,
                                        EventType.LIFECYCLE_CHANGED]):
        p = event.payload
        if event.type == EventType.EXPOSURE_DECIDED and p.get("exposed"):
            out.append(Edge("exposed_to", str(p.get("memory_id")),
                            f"agent:{event.agent_id or 'unknown'}", event.seq))
            if event.episode_id:
                out.append(Edge("exposed_to", str(p.get("memory_id")),
                                f"episode:{event.episode_id}", event.seq))
        elif event.type == EventType.MEMORY_CITED:
            out.append(Edge("relied_on", f"episode:{event.episode_id}", str(p.get("memory_id")),
                            event.seq))
        elif event.type == EventType.LIFECYCLE_CHANGED:
            if str(p.get("to")) in withdrawn:
                out.append(Edge("invalidated_by", str(p.get("memory_id")), f"event:{event.seq}",
                                event.seq))
        elif (event.type == EventType.ACTION_EXECUTED
              or (event.type == EventType.ACTION_GATED and p.get("allowed"))):
            for memory_id, _ in p.get("evidence") or ():
                out.append(Edge("authorized", str(memory_id), f"action:{event.seq}", event.seq))
    return out


def downstream(fabric: "MemoryFabric", memory_id: str,
               graph: Iterable[Edge] | None = None) -> set[str]:
    """Memories that descend from this one by derivation, summary, copy or import."""
    graph = list(edges(fabric) if graph is None else graph)
    children: dict[str, set[str]] = {}
    for e in graph:
        if e.type in ("derived_from", "summarized_from", "copied_from"):
            children.setdefault(e.target, set()).add(e.source)
    out: set[str] = set()
    stack = [memory_id]
    while stack:
        for child in children.get(stack.pop(), ()):
            if child not in out and child != memory_id:
                out.add(child)
                stack.append(child)
    return out


def impact(fabric: "MemoryFabric", memory_id: str) -> dict[str, Any]:
    """Potentially contaminated, actually retrieved and confirmed use, kept apart."""
    graph = edges(fabric)
    reach = {memory_id} | downstream(fabric, memory_id, graph)
    exposed = sorted({(e.source, e.target) for e in graph
                      if e.type == "exposed_to" and e.source in reach})
    agents = sorted({t for _, t in exposed if t.startswith("agent:")})
    cited = sorted({(e.source, e.target) for e in graph
                    if e.type == "relied_on" and e.target in reach})
    actions = sorted({(e.source, e.target) for e in graph
                      if e.type == "authorized" and e.source in reach})
    return {
        "memory_id": memory_id,
        "potentially_contaminated": {"memories": sorted(reach - {memory_id}),
                                     "agents": agents},
        "actually_retrieved": [{"memory": m, "by": t} for m, t in exposed],
        "confirmed_use": {"relied_on": [{"episode": ep, "memory": m} for ep, m in cited],
                          "authorized": [{"memory": m, "action": a} for m, a in actions]},
    }
