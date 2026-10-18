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
            "deliveries": deliveries, "outstanding": outstanding}


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
