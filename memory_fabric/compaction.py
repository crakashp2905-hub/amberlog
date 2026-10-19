"""Session compaction: one governed summary of what a session learned, for later sessions.

A long session leaves many memories. A later session with a context budget
cannot read them all, and forty near-duplicate turns compete badly in
retrieval. `compact_session` writes **one summary memory** for an episode.
It is built so that the summary cannot become a way around the store's
guarantees:

1. **It is a derivation, never a replacement.** The summary is written with
   `derive(method=consolidated)`, with every input as a versioned parent.
   Lineage, retraction and the influence graph follow it. A correction to
   any input contests the summary, and the summary inherits the lowest
   origin-bound authority among its inputs (`authority.py`), so a trusted
   summariser never launders an untrusted source.
2. **The originals stay.** Nothing is deleted or deprecated here, and
   retention does not retire a premise of an exposable memory
   (`MemoryFabric.sweep_retention`).
3. **Contradictions are kept, not resolved.** Inputs that give different
   values for one claim are written into the summary as a dispute, with
   every value and its source.
4. **Values are checked.** Every value stated by a usable input must appear
   in the summary, or the summary is refused (`CompactionRefused`). A
   summariser that drops a number cannot silently lose a fact.
5. **It passes the ingest screen** like any other write: an injection
   rewritten as an instruction is quarantined.

Inputs are the memories the session wrote (`source_episodes`) and the ones
it cited. Withdrawn and contested inputs are left out and listed in the
report; a summary is about what the session can still stand on.

The default summariser is extractive and deterministic. A model can be
passed as `summarise`, and its output goes through the same checks.
"""

from __future__ import annotations

__stability__ = "experimental"

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Callable, Sequence

from .conflicts import author, claim, find_conflicts
from .events import EventType
from .model import EXPOSABLE_STATES, ProvenanceMethod

if TYPE_CHECKING:  # pragma: no cover
    from .fabric import MemoryFabric
    from .model import Memory


class CompactionRefused(Exception):
    """The summary would lose or hide something; nothing was written."""


@dataclass
class CompactionReport:
    episode_id: str
    summary_id: str | None
    inputs: list[str] = field(default_factory=list)
    left_out: dict[str, str] = field(default_factory=dict)
    disputes: list[list[str]] = field(default_factory=list)


def session_memories(fabric: "MemoryFabric", episode_id: str) -> list["Memory"]:
    """What the session wrote, and what it cited, in log order."""
    ids: list[str] = [m.id for m in fabric.state.memories.values()
                      if episode_id in m.provenance.source_episodes]
    for event in fabric.log.read_types([EventType.MEMORY_CITED]):
        if event.episode_id == episode_id:
            mid = str(event.payload.get("memory_id"))
            if mid not in ids and mid in fabric.state.memories:
                ids.append(mid)
    return [fabric.state.memories[i] for i in ids]


def session_label(fabric: "MemoryFabric", episode_id: str) -> str:
    """The episode's task id, which names the session in its summary."""
    for event in fabric.log.read_types([EventType.EPISODE_STARTED]):
        if event.episode_id == episode_id:
            return str(event.payload.get("task_id") or episode_id)
    return episode_id


def extractive(memories: Sequence["Memory"], disputes: Sequence[Sequence["Memory"]]) -> str:
    """One line per distinct claim; disputed claims listed with every value and source.

    A claim is its identifiers and values (`conflicts.claim`): restatements of
    one claim keep only the shortest wording. A note with neither identifiers
    nor values ("shift handover went smoothly") is chatter and is dropped. The
    C1 pilot found the first version, which kept every distinct sentence, wrote
    summaries too long for any context budget.
    """
    disputed = {m.id for group in disputes for m in group}
    best: dict[object, str] = {}
    order: list[object] = []
    for memory in memories:
        if memory.id in disputed:
            continue
        ids, _, values = claim(memory.content)
        text = memory.content.strip()
        if not ids and not values:
            continue
        key = (ids, values) if (ids or values) else text.lower()
        if key not in best:
            order.append(key)
            best[key] = text
        elif len(text) < len(best[key]):
            best[key] = text
    lines = [best[k] for k in order]
    for group in disputes:
        lines.append("Disputed, unresolved: " + "; ".join(
            f"{m.content.strip()} (from {author(m)})" for m in group))
    return " ".join(lines)


def compact_session(fabric: "MemoryFabric", episode_id: str, agent_id: str,
                    summarise: Callable[[Sequence["Memory"], Sequence[Sequence["Memory"]]], str]
                    | None = None, scope: str | None = None) -> CompactionReport:
    """Write one governed summary of an episode. Returns what was used and left out."""
    report = CompactionReport(episode_id=episode_id, summary_id=None)
    usable = []
    for memory in session_memories(fabric, episode_id):
        if memory.lifecycle_state in EXPOSABLE_STATES:
            usable.append(memory)
        else:
            report.left_out[memory.id] = memory.lifecycle_state.value
    if not usable:
        raise CompactionRefused(f"episode {episode_id} has no usable memories to compact")
    disputes = find_conflicts(usable)
    report.disputes = [[m.id for m in g] for g in disputes]
    # Named by its session, so "what did shift 3 establish?" can find it;
    # the facts themselves name no session.
    text = f"Session summary ({session_label(fabric, episode_id)}): " +         (summarise or extractive)(usable, disputes)
    _, _, stated = claim(text)
    missing = sorted({v for m in usable for v in claim(m.content)[2]} - set(stated))
    if missing:
        raise CompactionRefused(f"the summary drops values the session recorded: {missing}")
    for group in disputes:
        for m in group:
            if not set(claim(m.content)[2]) <= set(stated):
                raise CompactionRefused("the summary resolves a dispute instead of keeping it")
    narrowest = min((m.scope for m in usable), key=lambda s: s.rank)
    report.summary_id = fabric.derive(
        agent_id, text, parents=[m.id for m in usable],
        method=ProvenanceMethod.CONSOLIDATED,
        context={"kind": "derived_claim", "compaction_of": episode_id},
        scope=scope or narrowest)
    report.inputs = [m.id for m in usable]
    return report


def stale_summaries(fabric: "MemoryFabric") -> list[tuple[str, str]]:
    """Compaction summaries withdrawn or contested because an input changed: (summary, episode)."""
    out = []
    for memory in fabric.state.memories.values():
        episode = (memory.context or {}).get("compaction_of")
        if episode and memory.lifecycle_state not in EXPOSABLE_STATES:
            newer = [m for m in fabric.state.memories.values()
                     if (m.context or {}).get("compaction_of") == episode
                     and m.lifecycle_state in EXPOSABLE_STATES]
            if not newer:
                out.append((memory.id, str(episode)))
    return out


def recompact(fabric: "MemoryFabric", agent_id: str) -> list[CompactionReport]:
    """Write a fresh summary for every episode whose summary lost an input.

    A correction to one input contests the whole summary, which is right: it
    states a value that is no longer believed. But it also hides every other
    fact the summary held, and the C1 pilot measured that cost. Re-compacting
    from the inputs still usable restores them; the old summary stays
    contested, in the log, for audit. The background manager runs it.
    """
    reports = []
    for _, episode in stale_summaries(fabric):
        try:
            reports.append(compact_session(fabric, episode, agent_id=agent_id))
        except CompactionRefused:
            continue
    return reports


def summary_for(fabric: "MemoryFabric", episode_id: str) -> "Memory | None":
    """The session's current, usable summary: what a handoff to a later session reads first."""
    found = [m for m in fabric.state.memories.values()
             if (m.context or {}).get("compaction_of") == episode_id
             and m.lifecycle_state in EXPOSABLE_STATES]
    return max(found, key=lambda m: m.created_at) if found else None

