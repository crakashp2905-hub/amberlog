"""Lineage graph and retraction propagation.

This is the truth-maintenance-system idea (Doyle 1979, de Kleer 1986) applied to
agent memory: when a memory is withdrawn, everything derived from it loses its
justification and must be re-examined. Without this, a poisoned memory survives
its own rollback through its descendants (SECURITY.md T5), which is why lineage
is a security requirement rather than a convenience.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Iterable

from .model import Memory
from .projections import ProjectionState


@dataclass
class LineageNode:
    memory_id: str
    depth: int
    memory: Memory | None = None


@dataclass
class LineageView:
    """What `explain()` and the dashboard render."""

    memory_id: str
    ancestors: list[LineageNode] = field(default_factory=list)
    descendants: list[LineageNode] = field(default_factory=list)
    source_episodes: list[str] = field(default_factory=list)
    versions: int = 1


def _walk(edges: dict[str, set[str]], roots: Iterable[str], state: ProjectionState) -> list[LineageNode]:
    """Breadth-first traversal recording the shortest distance to each node.

    Cycles cannot occur through well-formed provenance (a parent always predates
    its child), but `seen` makes the walk safe against a malformed log rather
    than trusting that invariant.
    """
    seen: set[str] = set(roots)
    queue: deque[tuple[str, int]] = deque((r, 0) for r in roots)
    out: list[LineageNode] = []
    while queue:
        current, depth = queue.popleft()
        for neighbour in sorted(edges.get(current, ())):
            if neighbour in seen:
                continue
            seen.add(neighbour)
            out.append(LineageNode(neighbour, depth + 1, state.memories.get(neighbour)))
            queue.append((neighbour, depth + 1))
    return out


class LineageGraph:
    """Read-only queries over the derivation edges held in the projection."""

    def __init__(self, state: ProjectionState) -> None:
        self._state = state

    def ancestors(self, memory_id: str) -> list[LineageNode]:
        """Memories this one was derived from, transitively."""
        return _walk(self._state.parents, [memory_id], self._state)

    def descendants(self, memory_id: str) -> list[LineageNode]:
        """Memories derived from this one, transitively. The retraction set."""
        return _walk(self._state.children, [memory_id], self._state)

    def view(self, memory_id: str) -> LineageView:
        memory = self._state.memories.get(memory_id)
        return LineageView(
            memory_id=memory_id,
            ancestors=self.ancestors(memory_id),
            descendants=self.descendants(memory_id),
            source_episodes=list(memory.provenance.source_episodes) if memory else [],
            versions=len(self._state.history.get(memory_id, ())) + (1 if memory else 0),
        )

    def evidence_is_independent(self, memory_ids: Iterable[str]) -> bool:
        """False when the memories share an ancestor.

        Counting agents is not evidence of independence: several agents can
        "confirm" a claim they all inherited from one source (SECURITY.md T3).
        Shared ancestry means correlated evidence.
        """
        ids = list(memory_ids)
        ancestor_sets = []
        for memory_id in ids:
            ancestors = {node.memory_id for node in self.ancestors(memory_id)}
            ancestors.add(memory_id)
            ancestor_sets.append(ancestors)
        for i in range(len(ancestor_sets)):
            for j in range(i + 1, len(ancestor_sets)):
                if ancestor_sets[i] & ancestor_sets[j]:
                    return False
        return True

    def roots(self, memory_id: str) -> list[str]:
        """Ancestors with no parents of their own: the original observations."""
        out = [
            node.memory_id
            for node in self.ancestors(memory_id)
            if not self._state.parents.get(node.memory_id)
        ]
        if not self._state.parents.get(memory_id):
            out.append(memory_id)
        return out
