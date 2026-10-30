"""Governed decay view: recent memories in full, older ones in summaries that coarsen with age.

The idea comes from OptMem (github.com/VictorTaelin/OptMem), as its README
describes it: an append-only log, a binary tree of summaries over it, a
bounded "wake" view in which detail fades with age, a "zoom" back down to the
records, and summaries written by the agent itself when a merge comes due
rather than by a background process. **No OptMem code is used**: upstream
ships no licence, so this is an original implementation of the idea, and it
differs where MemoryFabric's guarantees require it to:

- **Positions are fixed** over every memory of the tenant in log order,
  withdrawn ones included, so a withdrawal does not shift every block. A
  node covers the aligned range ``[lo, hi)`` of size ``2**k``.
- **Every node is checked at use.** A summary is served only while every
  memory it was written from is still at the recorded version and readable
  by the requesting agent now. Otherwise the view falls back to the node's
  halves, down to the admissible records: a withdrawn memory never reaches
  a wake view through a summary of it.
- **Agent summaries are derived memories** (`derive`, method
  `consolidated`), with every source as a versioned parent. They stay
  candidates, so retrieval never serves them as evidence, and lineage,
  retraction and erasure reach them like any derivation; erasing a source
  also erases every summary written from it (`erase_summaries_of`).
- **A submitted summary is checked before it is stored**: it may drop detail
  (summaries are lossy; zoom recovers the records) but may not state a
  number, identifier, date or negation that none of its sources state, and
  it passes the same ingest screen as any write.
- Where no agent summary exists, a deterministic extractive one is computed
  on the fly (never stored): the most recent statement of each distinct
  claim, cut to a length cap, with a count of what was left out.

Token costs are estimates (characters / 4).
"""

from __future__ import annotations

__stability__ = "experimental"

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Callable

from .conflicts import claim
from .context_map import estimate_tokens
from .identity import DEFAULT_TENANT
from .model import LifecycleState, ProvenanceMethod

if TYPE_CHECKING:  # pragma: no cover
    from .fabric import MemoryFabric
    from .model import Memory

SUMMARY_KEY = "decay_node"
MAX_SUMMARY_CHARS = 400
EXTRACTIVE_CHARS = 220
PER_LEVEL = 2
_NEGATIONS = frozenset({"not", "no", "never", "none", "cannot", "without", "disabled",
                        "isn't", "aren't", "wasn't", "doesn't", "don't", "won't", "can't"})
_WORD = re.compile(r"[A-Za-z']+")
_DATE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")


class SummaryRejected(Exception):
    """A submitted summary states something its sources do not, or failed a screen."""

    code = "SUMMARY_REJECTED"


def _facts(text: str) -> set[str]:
    ids, _, values = claim(text)
    words = {w.lower() for w in _WORD.findall(text)}
    return set(ids) | set(values) | (words & _NEGATIONS) | set(_DATE.findall(text))


@dataclass
class Piece:
    lo: int
    hi: int
    kind: str  # "record", "summary", "extractive", "hidden"
    text: str
    sources: list[str] = field(default_factory=list)
    summary_id: str | None = None

    @property
    def tokens(self) -> int:
        return estimate_tokens(self.text) if self.text else 0

    def to_json(self) -> dict[str, Any]:
        return {"node": f"{self.lo}-{self.hi}", "kind": self.kind, "text": self.text,
                "sources": self.sources, "summary_id": self.summary_id,
                "tokens_estimated": self.tokens}


def _cover(end: int, per_level: int = PER_LEVEL) -> list[tuple[int, int]]:
    """Aligned ranges covering [0, end), finest nearest `end`, coarsening backwards."""
    pieces: list[tuple[int, int]] = []
    pos, size = end, 2
    while pos > 0:
        for _ in range(per_level):
            if pos == 0:
                break
            s = size
            while s > 1 and (pos % s != 0 or pos - s < 0):
                s //= 2
            pieces.append((pos - s, pos))
            pos -= s
        size *= 2
    return list(reversed(pieces))


class DecayView:
    """One agent's view of one tenant's memory, under a token budget."""

    def __init__(self, fabric: "MemoryFabric", agent_id: str,
                 tenant_id: str = DEFAULT_TENANT,
                 extractive: Callable[[list["Memory"]], str] | None = None) -> None:
        self.fabric = fabric
        self.agent_id = agent_id
        self.tenant_id = tenant_id
        self._extract = extractive or extractive_summary

    # --- the timeline ---------------------------------------------------

    def timeline(self) -> list["Memory"]:
        """Every memory of the tenant except summaries, in log order (first version)."""
        state = self.fabric.state
        out = [m for m in state.memories.values()
               if m.tenant_id == self.tenant_id and SUMMARY_KEY not in (m.context or {})]

        # By the *current* version's time: a revision is appended, as a
        # correction is in an append-only log. Ordering by first version kept a
        # corrected fact at its old position, inside the coarsest summaries, so
        # the view buried exactly what had just changed (decay-view result).
        return sorted(out, key=lambda m: (m.created_at, m.id))

    def _admissible(self, memory: "Memory") -> bool:
        return (memory.id not in self.fabric.state.erased
                and self.fabric.use(memory.id, agent_id=self.agent_id,
                                    tenant_id=self.tenant_id, audit=False).usable)

    # --- summaries ------------------------------------------------------

    def _summaries(self) -> dict[tuple[int, int], list["Memory"]]:
        out: dict[tuple[int, int], list["Memory"]] = {}
        for m in self.fabric.state.memories.values():
            node = (m.context or {}).get(SUMMARY_KEY)
            if (isinstance(node, dict) and m.tenant_id == self.tenant_id
                    and m.lifecycle_state is LifecycleState.CANDIDATE):
                out.setdefault((int(node["lo"]), int(node["hi"])), []).append(m)
        for v in out.values():
            v.sort(key=lambda m: (-m.created_at, m.id))
        return out

    def _valid_summary(self, summary: "Memory", sources: list["Memory"]) -> bool:
        state = self.fabric.state.memories
        recorded = dict(summary.provenance.parents)
        if set(recorded) != {m.id for m in sources}:
            return False
        for mid, version in recorded.items():
            current = state.get(mid)
            if current is None or current.version != version or not self._admissible(current):
                return False
        return True

    def _render(self, lo: int, hi: int, line: list["Memory"],
                summaries: dict[tuple[int, int], list["Memory"]]) -> list[Piece]:
        block = line[lo:hi]
        visible = [m for m in block if self._admissible(m)]
        if hi - lo == 1:
            m = block[0]
            return [Piece(lo, hi, "record", m.content, [f"{m.id}@v{m.version}"])
                    if visible else Piece(lo, hi, "hidden", "")]
        if not visible:
            return [Piece(lo, hi, "hidden", "")]
        if len(visible) == len(block):
            for summary in summaries.get((lo, hi), ()):
                if self._valid_summary(summary, block):
                    return [Piece(lo, hi, "summary", summary.content,
                                  [f"{m.id}@v{m.version}" for m in block], summary.id)]
            return [Piece(lo, hi, "extractive", self._extract(block),
                          [f"{m.id}@v{m.version}" for m in block])]
        # Something in the block is not readable now: never summarise around it.
        mid = (lo + hi) // 2
        return self._render(lo, mid, line, summaries) + self._render(mid, hi, line, summaries)

    # --- the view -------------------------------------------------------

    def wake(self, budget: int = 2000, per_level: int = PER_LEVEL) -> list[Piece]:
        """The largest raw tail that fits, older memory summarised behind it.

        If even an all-summary view is over budget, it coarsens (one node per
        level), then drops the **oldest** nodes: the newest memory is the last
        thing a bounded view gives up. `zoom` and `retrieve` still reach what
        a view leaves out.
        """
        line = self.timeline()
        summaries = self._summaries()
        n = len(line)

        def layout(tail: int, levels: int) -> list[Piece]:
            pieces: list[Piece] = []
            for lo, hi in _cover(n - tail, levels):
                pieces += self._render(lo, hi, line, summaries)
            for i in range(n - tail, n):
                pieces += self._render(i, i + 1, line, summaries)
            return [p for p in pieces if p.kind != "hidden"]

        for tail in range(n, -1, -1):
            pieces = layout(tail, per_level)
            if sum(p.tokens for p in pieces) <= budget:
                return pieces
        pieces = layout(0, 1)
        while pieces and sum(p.tokens for p in pieces) > budget:
            pieces.pop(0)
        return pieces

    def zoom(self, lo: int, hi: int) -> list[Piece]:
        """A node's two halves, rendered under the same rules."""
        if hi - lo < 2:
            raise ValueError("a single record has no halves")
        line, summaries = self.timeline(), self._summaries()
        mid = (lo + hi) // 2
        return ([p for p in self._render(lo, mid, line, summaries) if p.kind != "hidden"]
                + [p for p in self._render(mid, hi, line, summaries) if p.kind != "hidden"])

    def render(self, pieces: list[Piece]) -> str:
        from .adapters.context import CLOSE, COMPACT_PREAMBLE, OPEN, _sanitise

        if not pieces:
            return ""
        body = "\n".join(f"#{p.lo}-{p.hi} {_sanitise(p.text)}" if p.hi - p.lo > 1
                         else f"#{p.lo} {_sanitise(p.text)}" for p in pieces)
        return f"{COMPACT_PREAMBLE}\n\n{OPEN}\n{body}\n{CLOSE}"

    # --- agent-written summaries ("nap") --------------------------------

    def pending(self, budget: int = 2000) -> list[dict[str, Any]]:
        """Nodes in the current view with no valid agent summary, and the records to summarise."""
        line = self.timeline()
        out = []
        for p in self.wake(budget):
            if p.kind == "extractive":
                out.append({"node": f"{p.lo}-{p.hi}",
                            "records": [m.content for m in line[p.lo:p.hi]],
                            "sources": p.sources})
        return out

    def submit(self, lo: int, hi: int, text: str, author: str | None = None) -> str:
        """Store an agent's summary of a node. Refused if it states anything its sources do not."""
        text = " ".join(text.split())
        if not text or len(text) > MAX_SUMMARY_CHARS:
            raise SummaryRejected(f"a summary is 1 to {MAX_SUMMARY_CHARS} characters")
        line = self.timeline()
        if not (0 <= lo < hi <= len(line)) or hi - lo < 2 or (hi - lo) & (hi - lo - 1) \
                or lo % (hi - lo):
            raise SummaryRejected(f"#{lo}-{hi} is not a node of the tree")
        block = line[lo:hi]
        if not all(self._admissible(m) for m in block):
            raise SummaryRejected("a record under this node is not readable now")
        invented = _facts(text) - set().union(*(_facts(m.content) for m in block))
        if invented:
            raise SummaryRejected(f"states what no source states: {sorted(invented)[:5]}")
        sid = self.fabric.derive(author or self.agent_id, text, parents=[m.id for m in block],
                                 method=ProvenanceMethod.CONSOLIDATED,
                                 context={SUMMARY_KEY: {"lo": lo, "hi": hi}},
                                 tenant_id=self.tenant_id, auto_activate=False)
        if self.fabric.get(sid).lifecycle_state is not LifecycleState.CANDIDATE:
            raise SummaryRejected(f"the summary failed the ingest screen "
                                  f"({self.fabric.get(sid).lifecycle_state.value})")
        return sid


def extractive_summary(block: list["Memory"]) -> str:
    """The latest fact-bearing statement per subject, newest first, cut to a cap.

    A statement with no value or identifier ("logbook signed") is counted,
    not quoted: it is what a bounded view can most afford to lose, and the
    first version, which quoted it, spent the budget on it and cut facts.
    """
    seen: set[Any] = set()
    lines: list[str] = []
    for m in sorted(block, key=lambda m: (-m.created_at, m.id)):
        ids, _, values = claim(m.content)
        if not values:
            continue
        key = ids or values
        if key in seen:
            continue
        seen.add(key)
        lines.append(m.content.strip())
    out: list[str] = []
    used = 0
    for text in lines:
        if used + len(text) > EXTRACTIVE_CHARS and out:
            break
        out.append(text)
        used += len(text) + 1
    left = len(block) - len(out)
    return " ".join(out) + (f" (+{left} more; zoom to read)" if left > 0 else "")


def erase_summaries_of(fabric: "MemoryFabric", memory_id: str, actor: str) -> list[str]:
    """Erase every summary written from this memory. Called by `erase_content`."""
    done = []
    for m in list(fabric.state.memories.values()):
        if (SUMMARY_KEY in (m.context or {}) or "compaction_of" in (m.context or {})) \
                and memory_id in dict(m.provenance.parents) \
                and m.id not in fabric.state.erased:
            fabric.erase_content(m.id, reason=f"a source ({memory_id}) was erased", actor=actor)
            done.append(m.id)
    return done
