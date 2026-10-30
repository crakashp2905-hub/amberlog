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

__stability__ = "experimental"

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


HALF_LIVES: tuple[float | None, ...] = (None, 200.0, 60.0, 20.0)
"""Candidate half-lives, in episodes of the same context, for `adaptive` (T1)."""


class TransferTrust:
    """Built from a store's log. Construct a fresh one to include later episodes.

    **Forgetting (T1, `research/prereg/t1-learned-staleness.md`).** S4 found
    that cumulative posteriors recover slowly when a context changes. That is
    the cost of never forgetting.

    - `half_life` discounts each observation by `0.5 ** (age / half_life)`,
      where age is the number of later episodes in the same context.
    - `adaptive=True` learns that rate **per context** from outcomes: for each
      context it keeps the candidate half-life whose posteriors would have
      best predicted that context's outcomes, each before it was seen
      (prequential log score). A stable context keeps its memory; a context
      that keeps changing learns to forget.
    """

    def __init__(self, fabric: "MemoryFabric", half_life: float | None = None,
                 adaptive: bool = False,
                 candidates: Sequence[float | None] = HALF_LIVES) -> None:
        self.fabric = fabric
        self.table: dict[tuple[str, str], Beta] = {}
        self.chosen: dict[str, float | None] = {}
        cited: dict[str, list[str]] = {}
        for event in fabric.log.read_types([EventType.MEMORY_CITED]):
            if event.episode_id:
                cited.setdefault(event.episode_id, []).append(event.payload["memory_id"])
        # Per context, in order: (cells the episode informs, outcome).
        history: dict[str, list[tuple[list[str], float]]] = {}
        for episode_id, episode in fabric.state.episodes.items():
            if episode.outcome is None:
                continue
            ctx = context_key(episode.context)
            origins = sorted({o for m in cited.get(episode_id, []) if (o := origin_of(fabric, m))})
            history.setdefault(ctx, []).append(
                (origins or [DEFAULT], max(0.0, min(1.0, episode.outcome))))
        for ctx, events in history.items():
            h = self._choose_half_life(events, candidates) if adaptive else half_life
            self.chosen[ctx] = h
            for cell, beta in self._fold(events, h).items():
                self.table[(cell, ctx)] = beta

    @staticmethod
    def _fold(events: list[tuple[list[str], float]], half_life: float | None) -> dict[str, Beta]:
        n = len(events)
        out: dict[str, Beta] = {}
        for i, (cells, success) in enumerate(events):
            w = 1.0 if half_life is None else 0.5 ** ((n - 1 - i) / half_life)
            for cell in cells:
                b = out.setdefault(cell, Beta())
                b.a += w * success
                b.b += w * (1.0 - success)
        return out

    @staticmethod
    def _choose_half_life(events: list[tuple[list[str], float]],
                          candidates: Sequence[float | None]) -> float | None:
        import math

        best, best_score = None, -math.inf
        for h in candidates:
            decay = 1.0 if h is None else 0.5 ** (1.0 / h)
            cells: dict[str, list[float]] = {}
            score = 0.0
            for chosen_cells, success in events:
                for cell in chosen_cells:
                    a, b = cells.get(cell, [1.0, 1.0])
                    p = a / (a + b)
                    score += math.log(max(1e-6, p if success >= 0.5 else 1.0 - p))
                # every cell in the context ages by one episode
                for v in cells.values():
                    v[0] = 1.0 + (v[0] - 1.0) * decay
                    v[1] = 1.0 + (v[1] - 1.0) * decay
                for cell in chosen_cells:
                    v = cells.setdefault(cell, [1.0, 1.0])
                    v[0] += success
                    v[1] += 1.0 - success
            if score > best_score:
                best, best_score = h, score
        return best

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
