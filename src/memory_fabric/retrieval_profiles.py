"""Retrieval profiles: one named setting per workload, not one global ranking.

A store used to rank every query the same way (`MemoryFabric(retrieval=...)`).
The measurements disagree about which way is best, and they disagree by
workload, not by store:

- **Lexical** wins on code-like lookups and short conversational turns:
  SciFact with the hashing embedder, 0.621 lexical against 0.558 hybrid;
  LongMemEval turn recall, 0.753 lexical against 0.693 hybrid.
- **Hybrid** wins once the embedder is a trained model: SciFact, 0.726
  against 0.621.
- **Lineage expansion and relations** help multi-hop questions (P1, P1d).
- **Review** workloads need contested memories, which an agent's lookup
  must not see.

So a profile is chosen per call (`retrieve(..., profile="multi_hop")`), and
any argument the caller passes explicitly wins over the profile. Both ranking
indexes are always maintained (`_index`), so changing the method changes how
results are ranked, never which memories exist. Custom profiles are
registered in `PROFILES`, or per store in `MemoryFabric.retrieval_profiles`.
"""

from __future__ import annotations

__stability__ = "beta"

from dataclasses import dataclass, field
from typing import Any

METHODS = ("lexical", "hybrid", "vector")


@dataclass(frozen=True)
class RetrievalProfile:
    name: str
    method: str | None = None
    """`lexical`, `hybrid` or `vector`; None keeps the store's default."""
    settings: dict[str, Any] = field(default_factory=dict)
    """`retrieve` keyword arguments this profile sets."""
    evidence: str = ""
    """Why: the measurement the setting rests on."""

    def __post_init__(self) -> None:
        if self.method is not None and self.method not in METHODS:
            raise ValueError(f"unknown method {self.method!r}; expected one of {METHODS}")


PROFILES: dict[str, RetrievalProfile] = {p.name: p for p in (
    RetrievalProfile("precise", "lexical", {"k": 5},
                     "lookups by code or name; lexical leads with a hashing embedder "
                     "(SciFact 0.621 against hybrid 0.558)"),
    RetrievalProfile("conversational", "lexical", {"k": 10},
                     "chat histories; lexical leads on LongMemEval turn recall "
                     "(0.753 against hybrid 0.693)"),
    RetrievalProfile("semantic", "hybrid", {"k": 8},
                     "paraphrased text with a trained embedder (SciFact hybrid 0.726 "
                     "against lexical 0.621); with the hashing embedder use `precise`"),
    RetrievalProfile("multi_hop", None, {"k": 8, "expand_lineage": 2, "follow_relations": True},
                     "questions whose answer spans linked memories (P1, P1d); for full chains "
                     "use `reconstruct`"),
    RetrievalProfile("audit", None, {"k": 20, "include_contested": True},
                     "review and investigation; shows contested memories that an agent "
                     "lookup withholds"),
)}


def resolve(name: str, custom: dict[str, RetrievalProfile] | None = None) -> RetrievalProfile:
    table = {**PROFILES, **(custom or {})}
    if name not in table:
        raise ValueError(f"unknown retrieval profile {name!r}; known: {', '.join(sorted(table))}")
    return table[name]
