"""Prometheus metrics for a store, from its own log: `GET /metrics` on `serve`.

Counters are folded incrementally from the log (only events since the last
scrape are read), so a scrape costs the size of what changed, not of the
store. Labels are reason codes, tools and lifecycle states, never memory
content or ids; agent ids are not labels either, since a label per agent is
unbounded cardinality.

    mf_memories{state="active"} 1203
    mf_events_total 48812
    mf_retrievals_total 9120
    mf_writes_total 1311
    mf_actions_total{tool="open_valve",allowed="false"} 3
    mf_refusals_total{reason="blocked_lifecycle"} 17
    mf_withdrawals_total{to="quarantined"} 4
"""

from __future__ import annotations

__stability__ = "beta"

import threading
from collections import Counter
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover
    from ..fabric import Amberlog

CONTENT_TYPE = "text/plain; version=0.0.4; charset=utf-8"


class StoreMetrics:
    def __init__(self) -> None:
        self._seq = 0
        self._lock = threading.Lock()
        self.retrievals = 0
        self.writes = 0
        self.actions: Counter[tuple[str, str]] = Counter()
        self.refusals: Counter[str] = Counter()
        self.withdrawals: Counter[str] = Counter()

    def _fold(self, fabric: "Amberlog") -> None:
        from ..events import EventType

        for e in fabric.log.read(since_seq=self._seq):
            if e.seq is not None:
                self._seq = max(self._seq, e.seq)
            p = e.payload
            if e.type == EventType.RETRIEVAL_PERFORMED:
                self.retrievals += 1
            elif e.type == EventType.MEMORY_CREATED:
                self.writes += 1
            elif e.type == EventType.ACTION_GATED:
                self.actions[(str(p.get("tool")), str(bool(p.get("allowed"))).lower())] += 1
            elif e.type == EventType.ACCESS_DENIED:
                self.refusals[str(p.get("reason_code"))] += 1
            elif e.type == EventType.LIFECYCLE_CHANGED and p.get("to") in (
                    "quarantined", "deprecated", "contested", "deleted"):
                self.withdrawals[str(p.get("to"))] += 1

    def render(self, fabric: "Amberlog") -> str:
        with self._lock:
            self._fold(fabric)
            states = Counter(m.lifecycle_state.value for m in fabric.state.memories.values())
            lines = [
                "# HELP mf_memories Memories by lifecycle state.",
                "# TYPE mf_memories gauge",
                *(f'mf_memories{{state="{_esc(s)}"}} {n}' for s, n in sorted(states.items())),
                "# HELP mf_events_total Events in the log.",
                "# TYPE mf_events_total counter",
                f"mf_events_total {fabric.log.head_seq or 0}",
                "# TYPE mf_retrievals_total counter",
                f"mf_retrievals_total {self.retrievals}",
                "# TYPE mf_writes_total counter",
                f"mf_writes_total {self.writes}",
                "# HELP mf_actions_total Gate decisions on protected tools.",
                "# TYPE mf_actions_total counter",
                *(f'mf_actions_total{{tool="{_esc(t)}",allowed="{a}"}} {n}'
                  for (t, a), n in sorted(self.actions.items())),
                "# HELP mf_refusals_total Memories refused to an agent, by reason.",
                "# TYPE mf_refusals_total counter",
                *(f'mf_refusals_total{{reason="{_esc(r)}"}} {n}'
                  for r, n in sorted(self.refusals.items())),
                "# TYPE mf_withdrawals_total counter",
                *(f'mf_withdrawals_total{{to="{_esc(t)}"}} {n}'
                  for t, n in sorted(self.withdrawals.items())),
            ]
            return "\n".join(lines) + "\n"


def _esc(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
