"""The Memory Control Center's read model: why, what acted, what depended, what is not covered.

Every function here **reads only**, because the dashboard writes nothing.
That rules out answering "why would retrieval show this?" by retrieving:
`retrieve` logs exposure decisions, and a browsing operator is not evidence
about any memory. So `eligibility` re-traces retrieval's filters one at a
time, in retrieval's own order, from the same projections and indexes. It
reports each one, so the first that fails is the reason a memory was left
out.
"""

from __future__ import annotations

__stability__ = "beta"

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover
    from ..fabric import MemoryFabric

STATIC = Path(__file__).parent / "static"


def eligibility(f: "MemoryFabric", memory_id: str, agent_id: str = "",
                tenant_id: str | None = None, query: str = "") -> dict[str, Any]:
    """Each retrieval filter, in order, for one memory: passed or not, and why."""
    from ..enforcement import RiskLevel
    from ..model import EXPOSABLE_STATES
    from ..validation import assess
    from ..vectors import MIN_RELEVANCE

    memory = f.state.memories.get(memory_id)
    if memory is None:
        return {"memory_id": memory_id, "eligible": False,
                "checks": [{"check": "exists", "passed": False, "detail": "no such memory"}]}
    checks: list[dict[str, Any]] = []

    def add(name: str, passed: bool, detail: str) -> None:
        checks.append({"check": name, "passed": bool(passed), "detail": detail})

    state = memory.lifecycle_state
    add("lifecycle", state in EXPOSABLE_STATES,
        f"{state.value}" + ("" if state in EXPOSABLE_STATES else
                            ": only active (or, when asked for, contested) memories are retrieved"))
    tenant = tenant_id or memory.tenant_id
    add("tenant", memory.tenant_id == tenant,
        f"memory in {memory.tenant_id}, asked for {tenant}")
    if agent_id:
        decision = f.enforcer.check(memory_id, risk=RiskLevel.LOW, agent_id=agent_id,
                                    tenant_id=tenant)
        add("visible to agent", decision.usable,
            f"{decision.verdict.value}: {decision.reason_code}")
    applicable = memory_id in f._applicable_at({memory_id}, None, None)
    add("valid now", applicable, "inside its validity window" if applicable
        else f"validity {memory.valid_from}–{memory.valid_to} excludes now")
    hostile = memory_id not in f._without_hostile_sources({memory_id})
    add("source not withheld", not hostile,
        "author not caught injecting" if not hostile
        else "its author was caught injecting; every memory it wrote is withheld")
    level = assess(f, memory_id).level
    add("claim check", level != "suspicious", f"claim check: {level}")
    eligible = all(c["passed"] for c in checks)
    out: dict[str, Any] = {"memory_id": memory_id, "eligible": eligible, "checks": checks}
    if query:
        scored = f.lexical.search(query, k=1, restrict_to={memory_id}, min_relevance=0.0)
        score = scored[0][1] if scored else 0.0
        pool = f._eligible_ids(tenant_id=tenant, agent_id=agent_id or None)
        ranked = [m for m, _ in f.lexical.search(query, k=max(len(pool), 1),
                                                 restrict_to=pool, min_relevance=MIN_RELEVANCE)]
        rank = ranked.index(memory_id) + 1 if memory_id in ranked else None
        add("matches the query", score > MIN_RELEVANCE,
            f"lexical score {score:.3f}" + ("" if score > MIN_RELEVANCE
                                            else ": shares no term with the query"))
        out.update({"query": query, "score": score, "rank": rank, "eligible_pool": len(pool),
                    "within_default_k": rank is not None and rank <= 5})
        out["eligible"] = all(c["passed"] for c in checks)
    out["first_blocker"] = next((c for c in checks if not c["passed"]), None)
    return out


def action_rows(f: "MemoryFabric", limit: int = 200) -> list[dict[str, Any]]:
    """Gate decisions, newest first: who asked to do what, and what the gate said."""
    from .. import events as ev

    rows = []
    for e in f.log.read_types([ev.EventType.ACTION_GATED]):
        p = e.payload
        rows.append({"seq": e.seq, "ts": e.ts, "agent_id": e.agent_id, "tool": p.get("tool"),
                     "allowed": p.get("allowed"), "reason_codes": p.get("reason_codes", []),
                     "claim_id": p.get("claim_id"), "evidence": len(p.get("evidence", []))})
    return list(reversed(rows))[:limit]


def action_detail(f: "MemoryFabric", seq: int) -> dict[str, Any]:
    """One decision with each piece of evidence as it was then and as it is now."""
    from .. import events as ev
    from ..validation import assess

    for e in f.log.read_types([ev.EventType.ACTION_GATED]):
        if e.seq != seq:
            continue
        p = dict(e.payload)
        evidence = []
        for mid, version in p.get("evidence", []):
            m = f.state.memories.get(mid)
            evidence.append({
                "memory_id": mid, "version_then": version,
                "version_now": m.version if m else None,
                "state_now": m.lifecycle_state.value if m else "missing",
                "claim_check_now": assess(f, mid).level if m else None,
                "content_now": m.content if m else None,
                "changed_since": bool(m) and (m.version != version
                                              or m.lifecycle_state.value != "active"),
            })
        return {"seq": e.seq, "ts": e.ts, "agent_id": e.agent_id, "decision": p,
                "evidence": evidence,
                "still_holds": all(not x["changed_since"] for x in evidence) if evidence else None}
    raise KeyError(seq)


def dependence(f: "MemoryFabric", memory_id: str) -> dict[str, Any]:
    """Which recorded decisions depended on this memory (`dependence.py`). Reads only."""
    from ..dependence import decisions_depending_on

    return decisions_depending_on(f, memory_id)


def limitations() -> list[dict[str, str]]:
    return json.loads((STATIC / "limitations.json").read_text(encoding="utf-8"))
