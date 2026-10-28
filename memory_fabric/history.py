"""What the store believed at a past point: "known at τ", as well as "true at t" (RQ3).

`retrieve(as_of=t)` answers *valid time*: what was true at t, by the windows
memories carry, as the store knows it **now**. An audit often asks the other
question: what would an agent have been told at log position τ, before later
recordings and corrections? That is *transaction time*, and it needs the log
replayed to τ, not the current state filtered.

    from memory_fabric.history import believed_at, seq_at
    tau = seq_at(fabric, ts_ms)                         # or a log sequence you hold
    for m in believed_at(fabric, "agent-a", "relief valve setting", tau, as_of=t):
        print(m.id, m.version, m.content)

Rules:

- **Same visibility as retrieval, at τ.** Lifecycle, tenant and scope are taken
  from the replayed state with the same `visible_to` rule `retrieve` uses, so a
  memory withdrawn after τ is returned (it was believed then) and one written
  after τ is not.
- **The version that stood at τ.** Content is decrypted for that version; a
  memory whose content has since been crypto-erased comes back with
  `content=None`, never with text.
- **An audit read, not an exposure.** Nothing is logged as exposed, because
  nothing reaches an agent's context: this is for reviewing what happened.
  Ranking is plain term overlap, deterministic and independent of the current
  index, which would otherwise rank by today's vocabulary.
"""

from __future__ import annotations

__stability__ = "experimental"

import re
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover
    from .fabric import MemoryFabric


@dataclass(frozen=True)
class Believed:
    id: str
    version: int
    content: str | None
    lifecycle_state: str
    score: float
    memory: Any


def seq_at(fabric: "MemoryFabric", ts_ms: int) -> int:
    """The last log position recorded at or before `ts_ms` (0 if none)."""
    last = 0
    for event in fabric.log.read():
        if event.ts is not None and event.ts <= ts_ms and event.seq is not None:
            last = max(last, event.seq)
    return last


def _terms(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9][a-z0-9-]+", text.lower()) if len(w) > 2}


def believed_at(fabric: "MemoryFabric", agent_id: str, query: str, seq: int, k: int = 10,
                as_of: int | None = None, tenant_id: str | None = None) -> list[Believed]:
    """Up to `k` memories the agent could have been shown at log position `seq`, best match first."""
    from .incident import replay_until
    from .model import BLOCKED_STATES, EXPOSABLE_STATES, visible_to

    if seq < 0:
        raise ValueError("seq must be a log position (>= 0)")
    state = replay_until(fabric, seq)
    q = _terms(query)
    out: list[Believed] = []
    for m in state.memories.values():
        if (m.lifecycle_state not in EXPOSABLE_STATES or m.lifecycle_state in BLOCKED_STATES
                or (tenant_id is not None and m.tenant_id != tenant_id)
                or not visible_to(m, agent_id, state)
                or (as_of is not None and not m.applies_at(as_of))):
            continue
        text: str | None = None
        if m.id not in fabric.state.erased and isinstance(m.content, str):
            try:
                text = fabric._unseal_content(m.content, m.id, m.version)
            except Exception:  # noqa: BLE001 - unreadable content is reported as absent
                text = None
        overlap = len(q & _terms(text or "")) / len(q) if q else 0.0
        if q and overlap == 0:
            continue
        out.append(Believed(m.id, m.version, text, m.lifecycle_state.value, round(overlap, 4),
                            replace(m, content=text)))
    out.sort(key=lambda b: (-b.score, b.id))
    return out[:k]
