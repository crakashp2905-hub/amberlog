"""Guided incident response: detect, assess the spread, contain, record.

One workflow over parts that already exist, so that under pressure an operator
follows a sequence instead of assembling one:

1. **detect** (`candidates`): memories the auditor's triggers, the ingest
   screens or the attention list point at, each with why.
2. **assess** (`assess`): who wrote it and what else that author wrote
   recently -- a bad source rarely writes one bad memory -- who has seen it,
   which stores hold a copy, what withdrawing it would contest (the
   correction preview, which is what quarantine does), and every gated action
   that used it as evidence, with whether it was a necessary source
   (`incident.reconstruct`).
3. **contain** (`contain`): withdraw it and owe the retraction to every store
   that received it, in one transaction; the author's other active memories
   come back as the next things to review.
4. **record** (`record`): a reviewable incident record generated from the log
   -- the timeline of every event touching the memory, the assessment, what
   was done and by whom, and what is still outstanding. Generated, not typed,
   so it cannot drift from what happened; content is redacted for secrets.

Read-only except `contain`.
"""

from __future__ import annotations

__stability__ = "beta"

import time
from typing import TYPE_CHECKING, Any

from .events import EventType
from .model import LifecycleState, WithdrawalBasis

if TYPE_CHECKING:  # pragma: no cover
    from .fabric import MemoryFabric

SIBLING_LIMIT = 20


def candidates(fabric: "MemoryFabric") -> list[dict[str, Any]]:
    from .auditor import Auditor
    from .observability.report import attention

    found: dict[str, list[str]] = {}
    for trigger in Auditor(fabric).scan():
        if trigger.subject in fabric.state.memories:
            found.setdefault(trigger.subject, []).append(f"auditor: {trigger.kind}"
                                                         + (f" ({trigger.detail})" if trigger.detail else ""))
    for memory_id, basis in fabric.state.withdrawal_basis.items():
        memory = fabric.state.memories.get(memory_id)
        if memory is not None and basis == WithdrawalBasis.SENSITIVE_DATA.value \
                and memory.lifecycle_state is LifecycleState.QUARANTINED:
            found.setdefault(memory_id, []).append("quarantined by an ingest screen")
    for item in attention(fabric):
        if item.memory_id and item.severity == "high":
            found.setdefault(item.memory_id, []).append(f"attention: {item.title}")
    return [{"memory_id": m, "why": sorted(set(w))} for m, w in sorted(found.items())]


def _actions_using(fabric: "MemoryFabric", memory_id: str) -> list[dict[str, Any]]:
    from .incident import reconstruct

    out = []
    for event in fabric.log.read_types([EventType.ACTION_GATED]):
        evidence = [m for m, _ in event.payload.get("evidence") or ()]
        if memory_id not in evidence:
            continue
        report = reconstruct(fabric, event.seq)
        necessary = next((s.necessary for s in report.sources if s.memory_id == memory_id), None)
        out.append({"seq": event.seq, "tool": event.payload.get("tool"), "agent": event.agent_id,
                    "allowed": bool(event.payload.get("allowed")), "necessary_source": necessary})
    return out


def assess(fabric: "MemoryFabric", memory_id: str) -> dict[str, Any]:
    from .correction import preview
    from .observability.report import safe_content
    from .reach import reach
    from .status import labels

    memory = fabric.state.memories[memory_id]
    author = memory.provenance.created_by
    siblings = sorted((m for m in fabric.state.memories.values()
                       if m.provenance.created_by == author and m.id != memory_id
                       and m.lifecycle_state is LifecycleState.ACTIVE),
                      key=lambda m: m.created_at or 0, reverse=True)[:SIBLING_LIMIT]
    r = reach(fabric, memory_id)
    return {
        "memory_id": memory_id,
        "content": safe_content(fabric, memory.content)[0],
        "author": author,
        "state": memory.lifecycle_state.value,
        "status": [label.to_json() for label in labels(fabric, memory_id)],
        "author_other_active": [m.id for m in siblings],
        "seen_by": r.seen_by,
        "stores": r.stores,
        "blast_radius": preview(fabric, memory_id).to_json(),
        "actions_using_it": _actions_using(fabric, memory_id),
    }


def contain(fabric: "MemoryFabric", memory_id: str, reason: str, actor: str) -> dict[str, Any]:
    from .correction import apply

    if fabric.state.memories[memory_id].lifecycle_state is LifecycleState.QUARANTINED:
        result: dict[str, Any] = {"memory_id": memory_id, "already_quarantined": True}
    else:
        result = apply(fabric, memory_id, reason=reason, actor=actor)
    result["review_next"] = assess(fabric, memory_id)["author_other_active"]
    return result


def record(fabric: "MemoryFabric", memory_id: str) -> dict[str, Any]:
    """The incident record: timeline, assessment, actions and what is outstanding."""
    from .correction import status

    timeline = []
    for event in fabric.log.read():
        payload = event.payload
        touches = (payload.get("memory_id") == memory_id
                   or payload.get("origin_memory_id") == memory_id
                   or (payload.get("memory") or {}).get("id") == memory_id
                   or memory_id in [m for m, _ in payload.get("evidence") or ()])
        if touches:
            timeline.append({"seq": event.seq, "ts": event.ts, "type": event.type,
                             "actor": event.agent_id,
                             "detail": {k: v for k, v in payload.items()
                                        if k in ("to", "from", "reason", "basis", "exposed",
                                                 "tool", "allowed", "recipients", "action")}})
    deliveries = status(fabric, memory_id)
    outstanding = [d for d in deliveries if d["state"] not in ("enforced", "verified")]
    return {"generated_ms": int(time.time() * 1000), "store_id": fabric.store_id,
            "assessment": assess(fabric, memory_id), "timeline": timeline,
            "deliveries": deliveries, "outstanding": outstanding,
            "verification": verify_recovery(fabric, memory_id)}


def influence(fabric: "MemoryFabric", memory_id: str) -> dict[str, Any]:
    """Exposure, reliance and action, kept apart.

    Retrieval alone is not influence. A memory shown to an agent is
    *exposure* (the exposure log). One the agent cited in an episode is
    *reliance* (`MemoryCited`). One that was evidence for a gated or executed
    tool call is *action*. They are separate questions, and an incident
    report that collapses them either overstates the damage or misses it.
    """
    exposed: dict[str, int] = {}
    relied: list[dict[str, Any]] = []
    acted: list[dict[str, Any]] = []
    for event in fabric.log.read_types([EventType.EXPOSURE_DECIDED, EventType.MEMORY_CITED,
                                        EventType.ACTION_GATED, EventType.ACTION_EXECUTED]):
        p = event.payload
        if event.type == EventType.EXPOSURE_DECIDED:
            if p.get("memory_id") == memory_id and p.get("exposed"):
                agent = event.agent_id or "unknown"
                exposed[agent] = exposed.get(agent, 0) + 1
        elif event.type == EventType.MEMORY_CITED:
            if p.get("memory_id") == memory_id:
                relied.append({"seq": event.seq, "agent": event.agent_id,
                               "episode": event.episode_id})
        elif memory_id in [m for m, _ in p.get("evidence") or ()]:
            acted.append({"seq": event.seq, "type": event.type, "tool": p.get("tool"),
                          "allowed": p.get("allowed"), "outcome": p.get("outcome")})
    return {"exposed_to": exposed, "relied_on_in": relied, "actions": acted}


def verify_recovery(fabric: "MemoryFabric", memory_id: str) -> dict[str, Any]:
    """Check, from the store's own state, whether a contained memory is contained.

    It does not trust that `contain` ran or what an operator says. Each check
    reads current state:

    1. the memory itself cannot be retrieved or used;
    2. every conclusion derived from it is withdrawn or contested, unless it
       still stands on independent support (`correction.preview`'s rules);
    3. every copy the store sent is confirmed withdrawn at its recipient.
       A pending, failed or offline peer is **unresolved**, never assumed done;
    4. any action that used it is listed for a person to judge. The store
       cannot undo an external side effect, so it never calls that resolved.

    `status` is `contained` only when 1–3 hold. With 4 non-empty it is
    `contained, actions need review`. Otherwise it is `unresolved`, with the
    reasons.
    """
    from .correction import status as delivery_status
    from .model import EXPOSABLE_STATES

    memory = fabric.state.memories.get(memory_id)
    unresolved: list[str] = []
    if memory is None:
        return {"memory_id": memory_id, "status": "unknown", "unresolved": ["no such memory"]}
    if memory.lifecycle_state in EXPOSABLE_STATES:
        unresolved.append(f"the memory is still {memory.lifecycle_state.value}")
    children = [m for m in fabric.state.memories.values()
                if any(pid == memory_id for pid, _ in m.provenance.parents)]
    still_active = []
    for child in children:
        if child.lifecycle_state in EXPOSABLE_STATES:
            others = [pid for pid, _ in child.provenance.parents if pid != memory_id
                      and fabric.state.memories.get(pid) is not None
                      and fabric.state.memories[pid].lifecycle_state in EXPOSABLE_STATES]
            if not others:
                still_active.append(child.id)
    if still_active:
        unresolved.append(f"{len(still_active)} derived memory(ies) still active with no other "
                          f"support: {', '.join(still_active[:5])}")
    peers = delivery_status(fabric, memory_id)
    pending = [d for d in peers if d["state"] not in ("enforced", "verified")]
    if pending:
        unresolved.append(f"{len(pending)} store(s) not confirmed: "
                          + ", ".join(f"{d.get('store_id', '?')} ({d['state']})" for d in pending))
    used = influence(fabric, memory_id)
    allowed_actions = [a for a in used["actions"] if a.get("allowed") or a.get("outcome") == "executed"]
    if unresolved:
        verdict = "unresolved"
    elif allowed_actions:
        verdict = "contained, actions need review"
    else:
        verdict = "contained"
    # The named recovery state (roadmap P1). `revalidated`: withdrawn once and
    # since reinstated by review, so containment is no longer the goal.
    # `pending_reconciliation`: only peers are outstanding, and the manager
    # retries them every cycle. `recovery_unverified`: something local is
    # unresolved, or an action used it and nobody can verify its effect.
    withdrawn_once = any(e.payload.get("memory_id") == memory_id
                         and str(e.payload.get("to")) in ("quarantined", "deprecated", "contested")
                         for e in fabric.log.read_types([EventType.LIFECYCLE_CHANGED]))
    if memory.lifecycle_state in EXPOSABLE_STATES and withdrawn_once:
        state = "revalidated"
    elif pending and len(unresolved) == 1:
        state = "pending_reconciliation"
    elif unresolved or allowed_actions:
        state = "recovery_unverified"
    else:
        state = "quarantined"
    return {"memory_id": memory_id, "status": verdict, "recovery_state": state,
            "unresolved": unresolved,
            "derived": [c.id for c in children], "stores": peers,
            "influence": used, "actions_to_review": allowed_actions}


def record_markdown(data: dict[str, Any]) -> str:
    a = data["assessment"]
    lines = [f"# Incident record: {a['memory_id']}", "",
             f"Generated from the event log of store `{data['store_id']}`. Content is shown with "
             "secrets redacted.", "", f"> {a['content']}", "",
             "## Assessment", "",
             f"- Author: `{a['author']}`; state now: **{a['state']}**",
             f"- Seen by: {', '.join(f'{k} x{v}' for k, v in a['seen_by'].items()) or 'nobody'}",
             f"- Other stores: {', '.join(s['store_id'] for s in a['stores']) or 'none'}",
             f"- Withdrawing it contests: {', '.join(a['blast_radius']['would_contest']) or 'nothing'}",
             f"- Still standing on independent support: "
             f"{', '.join(a['blast_radius']['would_survive']) or 'nothing'}",
             f"- Author's other active memories to review: "
             f"{', '.join(a['author_other_active']) or 'none'}", "",
             "## Actions that used it", ""]
    for act in a["actions_using_it"] or []:
        lines.append(f"- seq {act['seq']}: `{act['tool']}` by `{act['agent']}`, "
                     f"{'allowed' if act['allowed'] else 'refused'}, necessary source: "
                     f"{act['necessary_source']}")
    if not a["actions_using_it"]:
        lines.append("- none")
    lines += ["", "## Timeline", "", "| seq | event | actor | detail |", "|---|---|---|---|"]
    for t in data["timeline"]:
        lines.append(f"| {t['seq']} | {t['type']} | {t['actor'] or ''} | "
                     f"{', '.join(f'{k}={v}' for k, v in t['detail'].items())} |")
    lines += ["", "## Outstanding", ""]
    lines += [f"- {d['store_id']}: {d['state']}" for d in data["outstanding"]] or ["- nothing"]
    return "\n".join(lines) + "\n"
