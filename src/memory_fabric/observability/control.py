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
                "content_now": _safe(f, mid) if m else None,
                "changed_since": bool(m) and (m.version != version
                                              or m.lifecycle_state.value != "active"),
            })
        from ..reasons import fix, say, withdrawal

        explanation = []
        for x in evidence:
            if x["changed_since"] and x["state_now"] != "missing":
                who = withdrawal(f, x["memory_id"])
                explanation.append(
                    f"Since then, “{_short(x['content_now'] or '')}” "
                    + (f"was {who['to']} by {who['by']}" + (f": {who['reason']}" if who["reason"] else "")
                       if who else f"changed (now v{x['version_now']}, {x['state_now']})") + ".")
        for code in p.get("reason_codes", []):
            explanation.append(" ".join(filter(None, [say(code), fix(code)])))
        return {"seq": e.seq, "ts": e.ts, "agent_id": e.agent_id, "decision": p,
                "explanation": explanation, "evidence": evidence,
                "still_holds": all(not x["changed_since"] for x in evidence) if evidence else None}
    raise KeyError(seq)


def dependence(f: "MemoryFabric", memory_id: str) -> dict[str, Any]:
    """Which recorded decisions depended on this memory (`dependence.py`). Reads only."""
    from ..dependence import decisions_depending_on

    return decisions_depending_on(f, memory_id)


def limitations() -> list[dict[str, str]]:
    return json.loads((STATIC / "limitations.json").read_text(encoding="utf-8"))


# --- the story of a fact, and of a store ------------------------------------

def _safe(f: "MemoryFabric", memory_id: str | None) -> str:
    """Memory content for display, with any secret values masked (`report.safe_content`)."""
    from .report import safe_content

    memory = f.state.memories.get(memory_id or "")
    return safe_content(f, memory.content)[0] if memory else ""


def _short(text: str, limit: int = 70) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= limit else text[:limit - 1] + "…"


def _sentence(f: "MemoryFabric", e: Any, focus: str | None = None) -> dict[str, Any] | None:
    """One log event as a plain sentence, or None when it is not part of a story."""
    from .. import events as ev
    from ..reasons import say

    p = e.payload
    kind, text, mid = None, None, None
    if e.type == ev.EventType.MEMORY_CREATED:
        m = p.get("memory", {})
        mid = m.get("id")
        how = (m.get("provenance") or {}).get("method", "observed")
        parents = (m.get("provenance") or {}).get("parents") or []
        kind = "created"
        text = (f"{e.agent_id or (m.get('provenance') or {}).get('created_by')} "
                + ("derived" if parents else "imported" if how == "imported" else "recorded")
                + f" “{_short(_safe(f, mid))}”")
    elif e.type == ev.EventType.MEMORY_VERSIONED:
        mid = p.get("memory", {}).get("id")
        kind, text = "revised", f"{e.agent_id} revised it: {p.get('reason') or 'new version'}"
    elif e.type == ev.EventType.LIFECYCLE_CHANGED:
        mid, to = p.get("memory_id"), p.get("to")
        who = p.get("actor") or e.agent_id or "the system"
        kind = {"active": "validated", "quarantined": "withdrawn", "deprecated": "retired",
                "contested": "disputed", "deleted": "erased"}.get(to, to)
        reason = p.get("reason") or ""
        text = {"validated": f"{who} validated it",
                "withdrawn": f"{who} withdrew it" + (f": {reason}" if reason else ""),
                "retired": f"{who} retired it" + (f": {reason}" if reason else ""),
                "disputed": "it became disputed" + (f": {reason}" if reason else ""),
                "erased": f"{who} erased its content"}.get(kind, f"{who} moved it to {to}")
    elif e.type == ev.EventType.SCOPE_CHANGED:
        mid = p.get("memory_id")
        kind, text = "shared", f"{p.get('actor') or e.agent_id} shared it with the {p.get('to')}"
    elif e.type == ev.EventType.MEMORY_SHARED:
        mid = p.get("memory_id")
        kind, text = "sent", f"sent to store {p.get('recipient_store_id')}"
    elif e.type == ev.EventType.COPY_RECOGNISED:
        mid = p.get("original_memory_id") if focus == p.get("original_memory_id") else p.get("memory_id")
        kind, text = "copied", f"{e.agent_id} wrote a copy (counted as the same source)"
    elif e.type == ev.EventType.RETRACTION_APPLIED:
        mid = p.get("local_memory_id")
        kind, text = "retracted", f"retraction from store {p.get('origin_store_id')} applied"
    elif e.type == ev.EventType.ACCESS_DENIED:
        mid = p.get("memory_id")
        kind = "refused"
        text = f"{e.agent_id} was refused it: {say(p.get('reason_code', ''))}"
    elif e.type == ev.EventType.ACTION_GATED:
        ids = [x[0] for x in p.get("evidence", [])]
        if focus is not None and focus not in ids:
            return None
        mid = focus or (ids[0] if ids else None)
        allowed = p.get("allowed")
        kind = "action_allowed" if allowed else "action_blocked"
        codes = [c for c in p.get("reason_codes", []) if c != "allowed"]
        text = (f"{e.agent_id} was allowed to run {p.get('tool')} on it" if allowed else
                f"{e.agent_id} was blocked from {p.get('tool')}: "
                + " ".join(say(c).split(": ", 1)[-1] for c in codes[:2]))
    if kind is None:
        return None
    return {"seq": e.seq, "ts": e.ts, "kind": kind, "memory_id": mid, "text": text}


def timeline(f: "MemoryFabric", memory_id: str, limit: int = 200) -> dict[str, Any]:
    """The life of one fact, as sentences: made, shared, used, corrected, acted on.

    Exposures are summarised per agent rather than listed: a fact recalled
    four hundred times is one line, "recalled by planner ×400".
    """
    from .. import events as ev

    if memory_id not in f.state.memories:
        raise KeyError(memory_id)
    steps: list[dict[str, Any]] = []
    recalls: dict[str, int] = {}
    for e in f.log.read():
        p = e.payload
        if e.type == ev.EventType.EXPOSURE_DECIDED:
            if p.get("memory_id") == memory_id and p.get("exposed"):
                recalls[e.agent_id or "?"] = recalls.get(e.agent_id or "?", 0) + 1
            continue
        row = _sentence(f, e, focus=memory_id)
        if row is None:
            continue
        if row["memory_id"] == memory_id or (e.type == ev.EventType.COPY_RECOGNISED
                                             and p.get("original_memory_id") == memory_id):
            steps.append(row)
    if recalls:
        steps.append({"seq": None, "ts": None, "kind": "recalled", "memory_id": memory_id,
                      "text": "recalled by " + ", ".join(f"{a} ×{n}" for a, n in
                                                         sorted(recalls.items()))})
    memory = f.state.memories[memory_id]
    blocked = sum(1 for s in steps if s["kind"] == "action_blocked")
    allowed = sum(1 for s in steps if s["kind"] == "action_allowed")
    headline = (f"“{_short(_safe(f, memory_id))}” is {memory.lifecycle_state.value}"
                + (f"; {allowed} action(s) relied on it" if allowed else "")
                + (f", {blocked} blocked" if blocked else "") + ".")
    return {"memory_id": memory_id, "headline": headline, "steps": steps[:limit],
            "recalls": recalls}


def story(f: "MemoryFabric", after: int = 0, limit: int = 300) -> list[dict[str, Any]]:
    """The store's log as sentences, oldest first, for step-by-step replay."""
    out = []
    for e in f.log.read(since_seq=after):
        row = _sentence(f, e)
        if row is not None:
            out.append(row)
            if len(out) >= limit:
                break
    return out


def if_wrong(f: "MemoryFabric", memory_id: str) -> dict[str, Any]:
    """"What would change if this were wrong?" in one place, reading only."""
    from .. import events as ev
    from ..dependence import decisions_depending_on

    descendants = sorted({n.memory_id for n in f.lineage(memory_id).descendants})
    dep = decisions_depending_on(f, memory_id)
    stores = sorted({str(e.payload.get("recipient_store_id"))
                     for e in f.log.read_types([ev.EventType.MEMORY_SHARED])
                     if e.payload.get("memory_id") == memory_id})
    parts = []
    if descendants:
        parts.append(f"{len(descendants)} conclusion(s) built on it would be re-checked")
    if dep["depended"]:
        parts.append(f"{len(dep['depended'])} past decision(s) would need review")
    if dep["would_stand"]:
        parts.append(f"{len(dep['would_stand'])} decision(s) would stand on other evidence")
    if stores:
        parts.append(f"{len(stores)} other store(s) would get a retraction")
    summary = ("If this were wrong: " + "; ".join(parts) + ".") if parts else \
        "If this were wrong: nothing else rests on it yet."
    return {"memory_id": memory_id, "summary": summary, "descendants": descendants,
            "depended": dep["depended"], "would_stand": dep["would_stand"], "stores": stores}


# --- the graph and the agents ------------------------------------------------

def graph(f: "MemoryFabric", limit: int = 400) -> dict[str, Any]:
    """Memories as nodes and "built from" / "copy of" as edges, for the graph view.

    Bounded to `limit` memories, preferring those with lineage, then the most
    recent, so a large store still draws. Labels are content previews with
    secret values masked.
    """
    from .. import events as ev

    memories = f.state.memories
    children = f.state.children
    linked = {mid for mid, kids in children.items() if kids} | {
        mid for mid, m in memories.items() if m.provenance.parents}
    order = sorted(memories, key=lambda mid: (mid not in linked, -memories[mid].created_at))
    chosen = set(order[:limit])
    exposures: dict[str, int] = {}
    copies: list[tuple[str, str]] = []
    for e in f.log.read_types([ev.EventType.EXPOSURE_DECIDED, ev.EventType.COPY_RECOGNISED]):
        p = e.payload
        if e.type == ev.EventType.EXPOSURE_DECIDED:
            if p.get("exposed") and p.get("memory_id") in chosen:
                exposures[p["memory_id"]] = exposures.get(p["memory_id"], 0) + 1
        elif p.get("memory_id") in chosen and p.get("original_memory_id") in chosen:
            copies.append((p["original_memory_id"], p["memory_id"]))
    nodes = [{"id": mid, "label": _short(_safe(f, mid), 60), "state": m.lifecycle_state.value,
              "type": m.type.value, "author": m.provenance.created_by,
              "exposures": exposures.get(mid, 0)}
             for mid in order[:limit] for m in [memories[mid]]]
    edges = [{"from": parent, "to": mid, "kind": "derived"}
             for mid in chosen for parent, _ in memories[mid].provenance.parents if parent in chosen]
    edges += [{"from": a, "to": b, "kind": "copy"} for a, b in copies]
    return {"nodes": nodes, "edges": edges, "total": len(memories), "shown": len(nodes)}


def _terms(text: str) -> set[str]:
    from ..navigation import terms

    return terms(text)


def knowledge_map(f: "MemoryFabric", max_topics: int = 8, per_topic: int = 4,
                  limit: int = 5000) -> dict[str, Any]:
    """What the store knows, at a glance: memories grouped into a few named topics.

    A topic is a word most of its memories share, so its name says what it is
    about; each memory joins the commonest such word it contains. Within a
    topic the memories a person should see first are picked out: withdrawn or
    disputed ones, then the ones agents used most. Everything else is a count.
    Built for a view that must read without zooming, so it stays small:
    at most `max_topics` topics and `per_topic` named memories in each.
    """
    from .. import events as ev

    memories = f.state.memories
    ids = sorted(memories, key=lambda m: -memories[m].created_at)[:limit]
    text = {mid: _safe(f, mid) for mid in ids}
    terms = {mid: _terms(text[mid]) for mid in ids}
    df: dict[str, int] = {}
    for ts in terms.values():
        for t in ts:
            df[t] = df.get(t, 0) + 1
    n = len(ids)
    ceiling = max(2, int(0.6 * n)) if n >= 6 else n
    # Commonest first; on a tie the longer word, which is usually the more specific one.
    candidates = sorted((t for t, c in df.items() if 2 <= c <= ceiling),
                        key=lambda t: (-df[t], any(ch.isdigit() for ch in t), -len(t), t))
    topic_of: dict[str, str] = {}
    topics: list[tuple[str, list[str]]] = []
    for t in candidates:
        if len(topics) >= max_topics:
            break
        members = [mid for mid in ids if mid not in topic_of and t in terms[mid]]
        if len(members) < 2:
            continue
        for mid in members:
            topic_of[mid] = t
        topics.append((t, members))
    rest = [mid for mid in ids if mid not in topic_of]
    if rest:
        topics.append(("", rest))
        for mid in rest:
            topic_of[mid] = ""

    exposures: dict[str, int] = {}
    for e in f.log.read_types([ev.EventType.EXPOSURE_DECIDED]):
        mid = e.payload.get("memory_id")
        if e.payload.get("exposed") and mid in topic_of:
            exposures[mid] = exposures.get(mid, 0) + 1

    withdrawn = ("quarantined", "deprecated", "deleted")
    priority = {"quarantined": 0, "deprecated": 1, "contested": 2, "candidate": 3}

    def why(m: Any, uses: int) -> str:
        state = m.lifecycle_state.value
        if state in withdrawn:
            return "withdrawn"
        if state == "contested":
            return "disputed"
        if state == "candidate":
            return "waiting for review"
        return f"used {uses}×" if uses else "in use"

    out_topics: list[dict[str, Any]] = []
    for key, members in topics:
        states: dict[str, int] = {}
        for mid in members:
            st = memories[mid].lifecycle_state.value
            states[st] = states.get(st, 0) + 1
        co: dict[str, int] = {}
        for mid in members:
            for t in terms[mid]:
                if t != key:
                    co[t] = co.get(t, 0) + 1
        second = max(co, key=lambda t: (co[t], len(t), t)) if co else ""
        if key:
            label = key.capitalize() + (f" · {second}" if second and co[second] >= 2
                                        and co[second] * 2 >= len(members) else "")
        else:
            label = "Other"
        ranked = sorted(members, key=lambda mid: (priority.get(memories[mid].lifecycle_state.value, 9),
                                                  -exposures.get(mid, 0), -memories[mid].created_at))
        out_topics.append({
            "id": key or "_other", "label": label, "size": len(members), "states": states,
            "exposures": sum(exposures.get(mid, 0) for mid in members),
            "highlights": [{"id": mid, "label": _short(text[mid], 48),
                            "state": memories[mid].lifecycle_state.value,
                            "author": memories[mid].provenance.created_by,
                            "exposures": exposures.get(mid, 0),
                            "why": why(memories[mid], exposures.get(mid, 0))}
                           for mid in ranked[:per_topic]]})
    shown = {h["id"] for t in out_topics for h in t["highlights"]}
    tid = {mid: (topic_of[mid] or "_other") for mid in topic_of}
    between: dict[tuple[str, str], int] = {}
    memory_links = []
    for mid in topic_of:
        for parent, _ in memories[mid].provenance.parents:
            if parent not in topic_of:
                continue
            a, b = tid[parent], tid[mid]
            if a != b:
                pair = (min(a, b), max(a, b))
                between[pair] = between.get(pair, 0) + 1
            if parent in shown and mid in shown:
                memory_links.append({"from": parent, "to": mid})
    total_withdrawn = sum(1 for mid in ids if memories[mid].lifecycle_state.value in withdrawn)
    disputed = sum(1 for mid in ids if memories[mid].lifecycle_state.value == "contested")
    named = [t for t in out_topics if t["id"] != "_other"]
    summary = []
    if named:
        busiest = max(named, key=lambda t: (t["exposures"], t["size"]))
        summary.append(f"{n} memories in {len(named)} topic{'s' if len(named) != 1 else ''}. "
                       f"Agents use \u201c{busiest['label']}\u201d most.")
    elif n:
        summary.append(f"{n} memories, not yet enough shared words to group them into topics.")
    if total_withdrawn or disputed:
        worst = max(out_topics, key=lambda t: sum(t["states"].get(s, 0) for s in withdrawn + ("contested",)))
        summary.append(f"{total_withdrawn} withdrawn and {disputed} disputed; most of them in "
                       f"\u201c{worst['label']}\u201d.")
    else:
        summary.append("Nothing has been withdrawn or disputed.")
    if between:
        summary.append(f"{sum(between.values())} conclusion{'s' if sum(between.values()) != 1 else ''} "
                       "built from memories in another topic (the lines).")
    return {"topics": out_topics, "links": [{"from": a, "to": b, "weight": w} for (a, b), w in between.items()],
            "memory_links": memory_links, "summary": summary, "total": n}


def agents(f: "MemoryFabric") -> list[dict[str, Any]]:
    """One row per agent: what it wrote, recalled, was refused and did."""
    from .. import events as ev

    rows: dict[str, dict[str, Any]] = {}

    def row(agent: str | None) -> dict[str, Any] | None:
        if not agent:
            return None
        return rows.setdefault(agent, {"agent_id": agent, "writes": 0, "recalls": 0,
                                       "refused": 0, "actions_allowed": 0,
                                       "actions_blocked": 0, "withdrawn": 0, "last_ts": 0})

    authored: dict[str, str] = {}
    for e in f.log.read_types([ev.EventType.MEMORY_CREATED, ev.EventType.EXPOSURE_DECIDED,
                               ev.EventType.ACCESS_DENIED, ev.EventType.ACTION_GATED,
                               ev.EventType.LIFECYCLE_CHANGED]):
        p = e.payload
        if e.type == ev.EventType.LIFECYCLE_CHANGED:
            if p.get("to") == "quarantined" and (who := authored.get(p.get("memory_id", ""))):
                rows[who]["withdrawn"] += 1
            continue
        r = row(e.agent_id)
        if r is None:
            continue
        r["last_ts"] = max(r["last_ts"], e.ts or 0)
        if e.type == ev.EventType.MEMORY_CREATED:
            r["writes"] += 1
            authored[p.get("memory", {}).get("id", "")] = r["agent_id"]
        elif e.type == ev.EventType.EXPOSURE_DECIDED:
            r["recalls"] += 1 if p.get("exposed") else 0
        elif e.type == ev.EventType.ACCESS_DENIED:
            r["refused"] += 1
        elif p.get("allowed"):
            r["actions_allowed"] += 1
        else:
            r["actions_blocked"] += 1
    return sorted(rows.values(), key=lambda r: -r["last_ts"])
