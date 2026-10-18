"""Recipient-specific trust in a sender, per context, from this store's own outcomes (S4).

Research direction S4 (`research/prereg/s4-recipient-trust.md`).

A recipient has two pieces of evidence about an import, and only one of them
is about the recipient:

- **The sender's score** describes the sender's context. A sender whose
  lessons work at home can be systematically wrong somewhere else. Phase B
  measured negative transfer, and the store deliberately tells a recipient
  it has no value evidence for an import (`federation._inbound_check`).
- **The recipient's verified outcomes** on episodes where it relied on that
  sender's imports, in a given context. These are about the recipient.

Per-memory contrastive estimation (`estimators.DoublyRobustEstimator`) is the
right instrument once a memory has been exposed and withheld enough times
in a context. For a fresh import, which has been in very few episodes, it
answers "unknown" for a long time. S4's dev pilot measured that: about ten
visits per (memory, context) left the estimate unknown almost everywhere.
Transferability is mostly a property of **who wrote it and where it is being
used**, so this pools at that grain:

    trust(origin store, context) = Beta posterior over success when this store
                                   relied on (cited) an import from that origin
    default(context)             = Beta posterior over success when it relied
                                   on no import

Both come from the log: `MemoryCited` says what an episode relied on,
`OutcomeRecorded` says what happened, and the verifier is never the acting
agent (`record_outcome`). `choose` is Thompson sampling: it relies on the
candidate whose origin's sampled success beats both the other candidates' and
the sampled default.

What it cannot do, stated:

- It cannot tell a good lesson from a bad one by the same sender in the same
  context. Its grain is the sender.
- It learns only from episodes where it relied on that sender, so a sender it
  stopped trusting is re-tested only by sampling.
- It is opt-in. Nothing in retrieval calls it.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Mapping, Sequence

from .events import EventType
from .model import context_key

if TYPE_CHECKING:  # pragma: no cover
    from .fabric import MemoryFabric

DEFAULT = "(no import)"


@dataclass
class Beta:
    a: float = 1.0
    b: float = 1.0

    @property
    def mean(self) -> float:
        return self.a / (self.a + self.b)

    @property
    def n(self) -> float:
        return self.a + self.b - 2.0

    def sample(self, rng: random.Random) -> float:
        return rng.betavariate(self.a, self.b)


def origin_of(fabric: "MemoryFabric", memory_id: str) -> str | None:
    """The original store of an import, or None for a native memory."""
    from .independence import global_ref

    memory = fabric.state.memories.get(memory_id)
    if memory is None or not isinstance(memory.context.get("federation"), dict):
        return None
    return global_ref(fabric, memory_id)[0]


class TransferTrust:
    """Built from a store's log. Construct a fresh one to include later episodes."""

    def __init__(self, fabric: "MemoryFabric") -> None:
        self.fabric = fabric
        self.table: dict[tuple[str, str], Beta] = {}
        cited: dict[str, list[str]] = {}
        for event in fabric.log.read_types([EventType.MEMORY_CITED]):
            if event.episode_id:
                cited.setdefault(event.episode_id, []).append(event.payload["memory_id"])
        for episode_id, episode in fabric.state.episodes.items():
            if episode.outcome is None:
                continue
            ctx = context_key(episode.context)
            origins = {o for m in cited.get(episode_id, []) if (o := origin_of(fabric, m))}
            for origin in origins or {DEFAULT}:
                cell = self.table.setdefault((origin, ctx), Beta())
                success = max(0.0, min(1.0, episode.outcome))
                cell.a += success
                cell.b += 1.0 - success

    def trust(self, origin: str, context: Mapping[str, Any] | None) -> Beta:
        return self.table.get((origin, context_key(context)), Beta())

    def choose(self, candidates: Sequence[str], context: Mapping[str, Any] | None,
               rng: random.Random) -> str | None:
        """Which import to rely on, or None for the local default (Thompson sampling)."""
        best, best_draw = None, self.trust(DEFAULT, context).sample(rng)
        for memory_id in candidates:
            origin = origin_of(self.fabric, memory_id)
            if origin is None:
                continue
            draw = self.trust(origin, context).sample(rng)
            if draw > best_draw:
                best, best_draw = memory_id, draw
        return best
