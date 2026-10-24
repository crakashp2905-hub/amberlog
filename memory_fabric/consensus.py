"""Support for a claim, counted by independent source, not by agent.

When agents exchange claims, the easy count is "how many agents say so".
Five agents repeating what one of them read is one source, not five. Treated
as five, that becomes artificial consensus, which then outvotes a single
honest observation that contradicts it.

`support(fabric, claim_text)` collects every usable memory that states the
same claim (the `validation` same-claim rule: same identifiers, shared
parameter words) and groups them by value. For each value it reports:

- `agents`: who asserted it;
- `independent_sources`: distinct **source roots**. A restatement, a
  derivation, a recognised copy and an import share their original's root,
  so they add an agent without adding a source;
- `artificial`: true when more agents assert it than there are independent
  sources behind it. The value looks better supported than it is.

The leading value is chosen by independent sources, never by agent count, and
the tie case is reported as `contested`. A host or agent API should show
`independent_sources` wherever it would show "N agents agree".

**Limits, stated.** Roots come from copy recognition, which treats a memory
whose terms are contained in an earlier one's as a copy of it. So two honest
reports in identical or contained wording count as **one** source: under-
counting, never over-counting. Independently written reports, which word
things differently, count separately. Independence is source roots, so a paraphrase written
from memory with no recorded parent counts as independent. That is S2's
laundering case (`research/results/s2-launder-sim.md`), and `independence.py`
narrows it with exposure records (an author shown the original first is not
independent of it). Pass `exposure_aware=True` to apply that here as well.
"""

from __future__ import annotations

__stability__ = "beta"

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from .conflicts import author, claim

if TYPE_CHECKING:  # pragma: no cover
    from .fabric import MemoryFabric


@dataclass(frozen=True)
class ValueSupport:
    value: str
    memories: tuple[str, ...]
    agents: tuple[str, ...]
    independent_sources: int
    roots: tuple[str, ...] = field(default=())

    @property
    def artificial(self) -> bool:
        return len(self.agents) > self.independent_sources

    def to_json(self) -> dict[str, Any]:
        return {"value": self.value, "memories": list(self.memories), "agents": list(self.agents),
                "independent_sources": self.independent_sources, "artificial": self.artificial}


@dataclass(frozen=True)
class Support:
    claim: str
    values: tuple[ValueSupport, ...]
    leading: str | None
    contested: bool

    def to_json(self) -> dict[str, Any]:
        return {"claim": self.claim, "leading": self.leading, "contested": self.contested,
                "values": [v.to_json() for v in self.values]}


def _same_claim(a: tuple, b: tuple) -> bool:
    ids_a, words_a, _ = a
    ids_b, words_b, _ = b
    if not ids_a or ids_a != ids_b:
        return False
    need = min(2, len(words_a), len(words_b))
    return len(words_a & words_b) >= max(1, need)


def support(fabric: "MemoryFabric", claim_text: str, tenant_id: str | None = None,
            exposure_aware: bool = False) -> Support:
    """Who asserts which value for this claim, and from how many independent sources."""
    from .model import EXPOSABLE_STATES

    mine = claim(claim_text)
    by_value: dict[str, list[Any]] = {}
    for m in fabric.state.memories.values():
        if m.lifecycle_state not in EXPOSABLE_STATES:
            continue
        if tenant_id is not None and m.tenant_id != tenant_id:
            continue
        theirs = claim(m.content)
        if not theirs[2] or not _same_claim(mine, theirs):
            continue
        by_value.setdefault(",".join(sorted(theirs[2])), []).append(m)

    def roots_of(ms: list[Any]) -> set[str]:
        roots = {fabric.source_root(m.id) for m in ms}
        if exposure_aware:
            from .independence import Independence

            ind = Independence(fabric)
            merged: set[str] = set()
            for r in roots:
                informed = ind.informed_by(r)
                if not (informed & (roots - {r})):
                    merged.add(r)
            roots = merged or roots
        return roots

    values = []
    for value, ms in by_value.items():
        roots = roots_of(ms)
        values.append(ValueSupport(value, tuple(m.id for m in ms),
                                   tuple(sorted({author(m) for m in ms})), len(roots),
                                   tuple(sorted(roots))))
    values.sort(key=lambda v: (-v.independent_sources, v.value))
    leading = values[0].value if values else None
    contested = len(values) > 1 and values[0].independent_sources == values[1].independent_sources
    return Support(claim_text, tuple(values), None if contested else leading, contested)
