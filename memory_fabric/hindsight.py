"""Hindsight: a withdrawal changes what the store believes about the rest of a source (T2).

The temporal-reasoning review (2026-10-18) separated two claims. This is the
backward one. When a memory is withdrawn as **false**, the store has learned
something about its author, not only about that memory. Retraction acts on
the memory, and its derived conclusions, and stops there. The author's
*other* memories, which nothing has yet contradicted, stay exactly as
trusted as before.

A source caught by the prompt-injection screen counts as discredited too:
an author who injects is hostile, whatever their other notes look like.

`suspects` re-reads them in hindsight. Every active memory whose original
author (`conflicts.author`, so imports resolve to the writer) has had a
memory withdrawn on a falsity basis is suspect. A caller can then:

- **flag** them (`annotate`), so an agent sees that the source has been wrong
  before;
- **withhold** them (`withhold`) until someone reviews them.

**The cost, stated:** an honest author who made one honest mistake becomes a
suspect too, and so does every valid note they wrote. T2 measures that cost
with a control family, an honest technician with one withdrawn mistake, so
it is weighed rather than assumed away.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Iterable, Sequence

from .conflicts import author
from .events import EventType
from .model import LifecycleState

if TYPE_CHECKING:  # pragma: no cover
    from .fabric import MemoryFabric
    from .model import Memory

FALSITY = ("contradicted", "detected as false", "wrong", "poison", "prompt injection")
HOSTILE = ("prompt injection",)
"""Signals no honest author produces. A contradicted withdrawal can be an honest mistake."""
SUSPECT = "[SOURCE WAS WRONG BEFORE: another note by this author was withdrawn as false]"


def discredited_authors(fabric: "MemoryFabric", signals: Sequence[str] = FALSITY) -> set[str]:
    """Authors with a memory withdrawn on one of these grounds.

    `signals=HOSTILE` discredits only sources caught doing something no honest
    author does (T2's dev pilot: discrediting on any falsity withheld every
    valid note by an honest technician who made one mistake).
    """
    out: set[str] = set()
    for event in fabric.log.read_types([EventType.LIFECYCLE_CHANGED]):
        payload = event.payload
        if payload.get("to") not in (LifecycleState.QUARANTINED.value,
                                      LifecycleState.DEPRECATED.value):
            continue
        # Both fields: a recipient records the basis as `retracted_at_origin`
        # and the origin's basis in the reason, so reading the basis alone
        # missed every cross-store withdrawal (found on T2's dev world).
        said = f"{payload.get('basis') or ''} {payload.get('reason') or ''}".lower()
        if not any(word in said for word in signals):
            continue
        memory = fabric.state.memories.get(payload.get("memory_id", ""))
        if memory is not None:
            out.add(author(memory))
    return out


def suspects(fabric: "MemoryFabric", memories: Iterable["Memory"] | None = None,
             signals: Sequence[str] = FALSITY) -> set[str]:
    """Ids of active memories whose author has been discredited."""
    bad = discredited_authors(fabric, signals)
    pool = fabric.state.memories.values() if memories is None else memories
    return {m.id for m in pool
            if m.lifecycle_state is LifecycleState.ACTIVE and author(m) in bad}


def annotate(fabric: "MemoryFabric", memories: Sequence["Memory"]) -> list[str]:
    flagged = suspects(fabric, memories)
    return [f"{SUSPECT} {m.content}" if m.id in flagged else m.content for m in memories]


def withhold(fabric: "MemoryFabric", memories: Sequence["Memory"],
             signals: Sequence[str] = FALSITY) -> list[str]:
    flagged = suspects(fabric, memories, signals)
    return [m.content for m in memories if m.id not in flagged]
