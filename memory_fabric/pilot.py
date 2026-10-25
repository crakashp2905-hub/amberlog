"""`memory-fabric pilot-report`: what a pilot showed, from the store's own log.

A team piloting Memory Fabric with their real agents can send back this
report instead of their data. It holds counts, durations and pseudonymous
ids only: no memory content, no queries, no agent names (each is replaced by
a keyed hash unless `--names` is given).

What it measures, all from recorded events:

- **acted on evidence later withdrawn**: allowed actions whose evidence was
  withdrawn afterwards. The harm a correction arrives too late for.
- **blocked after a correction**: actions refused because their evidence was
  withdrawn, provisional, suspicious or not fresh. The harm prevented.
- **exposure after withdrawal**: times a withdrawn memory was still shown to an
  agent after its withdrawal (should be 0; anything else is a defect to report).
- **correction lag**: for each withdrawn memory, time from its last use in an
  allowed action to its withdrawal, and from withdrawal to the last blocked
  attempt on it (how long agents kept trying).
- per agent: writes, recalls, refusals, actions allowed and blocked.
"""

from __future__ import annotations

__stability__ = "beta"

import hashlib
import hmac
import os
import statistics
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover
    from .fabric import MemoryFabric

WITHDRAWN = ("quarantined", "deprecated", "deleted")
EVIDENCE_REFUSALS = ("evidence_withdrawn", "dependency_withdrawn", "evidence_provisional",
                     "evidence_suspicious", "evidence_not_fresh", "evidence_version_moved",
                     "insufficient_independent_support")


def report(fabric: "MemoryFabric", names: bool = False, salt: bytes | None = None) -> dict[str, Any]:
    from .events import EventType

    key = salt or os.urandom(16)

    def who(agent: str | None) -> str:
        if not agent:
            return "-"
        return agent if names else "agent-" + hmac.new(key, agent.encode(), hashlib.sha256).hexdigest()[:8]

    withdrawn_at: dict[str, int] = {}
    allowed_on: dict[str, list[int]] = {}
    blocked_on: dict[str, list[int]] = {}
    exposed_after = 0
    agents: dict[str, dict[str, int]] = {}
    acted_then_withdrawn: set[int] = set()
    blocked_after_correction = 0
    allowed_actions = 0
    first_ts = last_ts = None

    def row(agent: str | None) -> dict[str, int]:
        return agents.setdefault(who(agent), {"writes": 0, "recalls": 0, "refusals": 0,
                                              "allowed": 0, "blocked": 0})

    for e in fabric.log.read():
        ts = e.ts or 0
        first_ts = ts if first_ts is None else first_ts
        last_ts = ts
        p = e.payload
        if e.type == EventType.MEMORY_CREATED:
            row(e.agent_id)["writes"] += 1
        elif e.type == EventType.EXPOSURE_DECIDED and p.get("exposed"):
            row(e.agent_id)["recalls"] += 1
            if p.get("memory_id") in withdrawn_at:
                exposed_after += 1
        elif e.type == EventType.ACCESS_DENIED:
            row(e.agent_id)["refusals"] += 1
        elif e.type == EventType.LIFECYCLE_CHANGED and p.get("to") in WITHDRAWN:
            withdrawn_at.setdefault(str(p.get("memory_id")), ts)
        elif e.type == EventType.ACTION_GATED:
            ids = [x[0] for x in p.get("evidence", [])]
            if p.get("allowed"):
                allowed_actions += 1
                row(e.agent_id)["allowed"] += 1
                for mid in ids:
                    allowed_on.setdefault(mid, []).append(e.seq or 0)
            else:
                row(e.agent_id)["blocked"] += 1
                if set(p.get("reason_codes", [])) & set(EVIDENCE_REFUSALS):
                    blocked_after_correction += 1
                for mid in ids:
                    blocked_on.setdefault(mid, []).append(ts)
    times = {e.seq: e.ts for e in fabric.log.read_types([EventType.ACTION_GATED])}
    for mid, seqs in allowed_on.items():
        if mid in withdrawn_at:
            acted_then_withdrawn.update(s for s in seqs if (times.get(s) or 0) <= withdrawn_at[mid])
    lag_before, lag_after = [], []
    for mid, wts in withdrawn_at.items():
        used = [times.get(s) or 0 for s in allowed_on.get(mid, [])]
        if used:
            lag_before.append((wts - max(used)) / 1000)
        tried = [t for t in blocked_on.get(mid, []) if t >= wts]
        if tried:
            lag_after.append((max(tried) - wts) / 1000)

    def med(xs: list[float]) -> float | None:
        return round(statistics.median(xs), 1) if xs else None

    return {
        "format": "mf-pilot-report/1",
        "store_id_hash": hashlib.sha256(fabric.store_id.encode()).hexdigest()[:16],
        "span_days": round(((last_ts or 0) - (first_ts or 0)) / 86_400_000, 2),
        "memories": len(fabric.state.memories),
        "withdrawn": len(withdrawn_at),
        "actions_allowed": allowed_actions,
        "acted_on_evidence_later_withdrawn": len(acted_then_withdrawn),
        "blocked_on_evidence": blocked_after_correction,
        "exposures_after_withdrawal": exposed_after,
        "median_seconds_last_use_to_withdrawal": med(lag_before),
        "median_seconds_withdrawal_to_last_blocked_try": med(lag_after),
        "agents": agents,
    }
