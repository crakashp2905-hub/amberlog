"""Evidence independence from exposure: who could have copied whom.

Research direction S2 (`research/prereg/s2-evidence-independence.md`).

## The gap

Corroboration needs independent sources. The store tells copies apart from
independent reports in two ways, and both look at what was *written*:

- **lineage** (`source_root`): a conclusion derived from a premise shares the
  premise's root;
- **content** (`duplicates`): a re-ingested document is a term subset of its
  original.

A paraphrase passes both. An agent that read report A and writes "the pump at
site 4 is failing" in its own words, with no parent recorded, is a second root
and a second vote. That is copy laundering. Run through a second store it
also loses its connection to A: the copy that arrives names only the store it
came through.

## What this adds

The store already logs every exposure, with its propensity, because causal
credit needs it (AGENTS.md principle 4). That record answers a different
question from wording: **had this memory's author been shown that evidence
before writing it?** If B's author was exposed to A, or to anything resting on
A's source, before B existed, then B is not independent of A, however B is
worded. The test is causal opportunity, not similarity, so a paraphrase cannot
evade it.

Across stores, an import carries the sources its author had been exposed to
(`context.federation.informed_by`, set by `federation.offer`), named by their
original store and id (`global_ref`). So the dependency survives the hop.

## What it cannot see, stated

- **Influence outside the store.** Two agents agreeing on a story over another
  channel leave no exposure, so the test cannot detect collusion. Nothing
  that reads only the store can.
- **An exposed author who observed independently anyway.** The test cannot
  tell that apart from a copy, so it errs toward "dependent". That costs
  corroboration that was real. S2 measures this cost as a family of its own
  rather than leaving it out.

Opt-in. Nothing in retrieval or the firewall calls this yet. AGENTS.md
principle 9 applies: that waits on S2's result.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Iterable, Sequence

if TYPE_CHECKING:  # pragma: no cover
    from .fabric import MemoryFabric

Ref = tuple[str, str]
"""(store id, memory id) of an original observation, the same in every store."""

ORIGIN_KEY = "federation"


def global_ref(fabric: "MemoryFabric", memory_id: str) -> Ref:
    """The original observation this memory is evidence from, named portably.

    Its local source root (lineage and recognised copies resolved), and when
    that root is an import, the original store and id it was imported from.
    """
    root = fabric.source_root(memory_id)
    origin = fabric.state.memories[root].context.get(ORIGIN_KEY)
    if isinstance(origin, dict):
        named = origin.get("root")
        first: dict[str, object] = named if isinstance(named, dict) else origin
        store, original = first.get("store"), first.get("memory_id")
        if isinstance(store, str) and isinstance(original, str):
            return (store, original)
    return (fabric.store_id, root)


class Independence:
    """One store's view of which memories could have informed which.

    Built from the projection, without reading the log. Construct a fresh one
    after writes, because it does not follow the store.
    """

    def __init__(self, fabric: "MemoryFabric") -> None:
        self.fabric = fabric
        self._seen: dict[str, list[tuple[int, str]]] = {}
        for record in fabric.state.exposures:
            if record.exposed and record.agent_id is not None:
                self._seen.setdefault(record.agent_id, []).append((record.seq, record.memory_id))
        self._informed: dict[str, frozenset[Ref]] = {}

    def informed_by(self, memory_id: str) -> frozenset[Ref]:
        """The original observations this memory's author had been shown first.

        Transitive: an author who was shown P, which was itself written by
        someone shown A, was informed by A too.
        """
        if memory_id in self._informed:
            return self._informed[memory_id]
        self._informed[memory_id] = frozenset()  # a cycle resolves to what is known
        memory = self.fabric.state.memories[memory_id]
        out: set[Ref] = set()
        origin = memory.context.get(ORIGIN_KEY)
        if isinstance(origin, dict):
            # An import's author worked elsewhere, so only what it carried counts.
            for ref in origin.get("informed_by") or ():
                if isinstance(ref, (list, tuple)) and len(ref) == 2:
                    out.add((str(ref[0]), str(ref[1])))
        else:
            created = self.fabric.state.created_seq.get(memory_id, 0)
            for seq, seen in self._seen.get(memory.provenance.created_by, ()):
                if seq < created and seen != memory_id and seen in self.fabric.state.memories:
                    out.add(global_ref(self.fabric, seen))
                    out |= self.informed_by(seen)
        result = frozenset(out - {global_ref(self.fabric, memory_id)})
        self._informed[memory_id] = result
        return result

    def dependent(self, left: str, right: str) -> bool:
        """Whether either could have been written from the other's evidence."""
        a, b = global_ref(self.fabric, left), global_ref(self.fabric, right)
        if a == b:
            return True
        return a in self.informed_by(right) or b in self.informed_by(left)

    def sources(self, memory_ids: Sequence[str]) -> list[str]:
        """The members that count as independent sources, one per original.

        A member counts unless its author had been shown another member's
        evidence before writing it. Then it is one source deduplicated by
        original (`global_ref`). This is deliberately not "join everything
        dependent": one summary written from two independent reports depends
        on both, and joining through it would merge two real observers into
        one. The summary drops out, and the two reports still count.

        Never empty for a non-empty input. If every member was informed by
        another, which only an exposure cycle can produce, the earliest
        written stands for the set.
        """
        ids = list(dict.fromkeys(memory_ids))
        refs = {m: global_ref(self.fabric, m) for m in ids}
        kept: dict[Ref, str] = {}
        for m in ids:
            others = {refs[o] for o in ids if refs[o] != refs[m]}
            if not (self.informed_by(m) & others):
                kept.setdefault(refs[m], m)
        if not kept and ids:
            first = min(ids, key=lambda m: self.fabric.state.created_seq.get(m, 0))
            return [first]
        return list(kept.values())


def independent_sources(fabric: "MemoryFabric", memory_ids: Iterable[str]) -> int:
    """How many independent sources these memories amount to."""
    return len(Independence(fabric).sources(list(memory_ids)))
