"""Context receipts: what an agent was given, what was left out and why, reproducibly.

`build_context` plans a bundle under a token budget (`context_map.plan`),
renders it as untrusted evidence, and records a **receipt** as a
`ContextBuilt` event (docs/architecture/ADR-003-context-receipts.md):

- `selected`: each memory as `id` + `version`, each summary node with its
  `source_digest` and the exact source versions it expands to;
- `excluded`: each candidate left out, with a reason code
  (`CONTESTED`, `WITHHELD_BY_POLICY`, `OVER_BUDGET`, `SUMMARY_STALE`,
  `SUMMARY_BLOCKED`, `COVERED_BY_SUMMARY`);
- `request_digest`: SHA-256 of the query. **The query itself is never
  stored**, and neither is any memory or summary text;
- the token budget and estimated use, the mode, the exposure `policy_id`,
  a digest of the retrieval configuration, the log head it was built at,
  and what is not reproducible (`nondeterminism`).

`explain_receipt` reads a receipt back and says, for every selected item,
whether it would still be admissible **now**. A receipt records what was
delivered; it never makes a memory usable again.
"""

from __future__ import annotations

__stability__ = "experimental"

import hashlib
import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from . import events as ev
from .adapters.context import COMPACT_PREAMBLE, OPEN, CLOSE, _sanitise
from .context_map import CONFIG_DIGEST, ContextMap, ContextPlan
from .events import EventType
from .identity import DEFAULT_TENANT
from .ids import new_ulid

if TYPE_CHECKING:  # pragma: no cover
    from .fabric import MemoryFabric


@dataclass
class ContextBundle:
    text: str
    receipt: dict[str, Any]
    plan: ContextPlan


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def retrieval_config(fabric: "MemoryFabric") -> str:
    return _sha(json.dumps({"retrieval": getattr(fabric, "retrieval_mode", "lexical"),
                            "rerank": bool(getattr(fabric, "rerank", False)),
                            "context_map": CONFIG_DIGEST}, sort_keys=True))


def render(plan: ContextPlan) -> str:
    if not plan.items:
        return ""
    body = "\n\n".join(_sanitise(i.content) for i in plan.items)
    return f"{COMPACT_PREAMBLE}\n\n{OPEN}\n{body}\n{CLOSE}"


def build_context(fabric: "MemoryFabric", agent_id: str, query: str, budget: int = 2000,
                  mode: str = "auto", tenant_id: str = DEFAULT_TENANT,
                  branch: str = "main", commit_id: str | None = None,
                  context_map: ContextMap | None = None) -> ContextBundle:
    """Plan, render and record one context bundle. Returns the text and its receipt."""
    cmap = context_map or ContextMap(fabric)
    plan = cmap.plan(agent_id, query, budget=budget, mode=mode, tenant_id=tenant_id,
                     branch=branch)
    receipt = {
        "receipt_id": f"ctx_{new_ulid()}",
        "tenant_id": tenant_id,
        "agent_id": agent_id,
        "branch": branch,
        "commit_id": commit_id,
        "request_digest": _sha(query),
        "selected": [i.ref() for i in plan.items],
        "excluded": plan.excluded,
        "token_budget": budget,
        "tokens_estimated": plan.tokens,
        "mode": plan.mode,
        "policy_id": plan.policy_id,
        "retrieval_config": retrieval_config(fabric),
        "log_head": fabric.log.head_seq,
        "nondeterminism": ("model reranker" if getattr(fabric, "rerank", False) else "none"),
    }
    fabric._emit(ev.context_built(fabric.now(), agent_id, receipt))
    return ContextBundle(text=render(plan), receipt=receipt, plan=plan)


def receipts(fabric: "MemoryFabric", tenant_id: str | None = None,
             agent_id: str | None = None) -> list[dict[str, Any]]:
    out = []
    for event in fabric.log.read_types([EventType.CONTEXT_BUILT]):
        r = event.payload
        if tenant_id is not None and r.get("tenant_id") != tenant_id:
            continue
        if agent_id is not None and r.get("agent_id") != agent_id:
            continue
        out.append(dict(r))
    return out


def get_receipt(fabric: "MemoryFabric", receipt_id: str,
                tenant_id: str | None = None) -> dict[str, Any] | None:
    for r in receipts(fabric, tenant_id=tenant_id):
        if r["receipt_id"] == receipt_id:
            return r
    return None


def explain_receipt(fabric: "MemoryFabric", receipt_id: str,
                    tenant_id: str | None = None) -> dict[str, Any]:
    """The receipt, with each selected item's admissibility now."""
    r = get_receipt(fabric, receipt_id, tenant_id=tenant_id)
    if r is None:
        raise KeyError(receipt_id)
    state = fabric.state.memories
    items = []
    for item in r["selected"]:
        refs = ([(item["id"], item.get("version"))] if item["kind"] == "memory" else
                [(s.split("@v")[0], int(s.split("@v")[1])) for s in item.get("expanded_sources", [])])
        problems = []
        for memory_id, version in refs:
            current = state.get(memory_id)
            if current is None:
                problems.append(f"{memory_id}: unknown here")
                continue
            if not fabric.use(memory_id, agent_id=r["agent_id"], tenant_id=r["tenant_id"],
                              audit=False).usable:
                problems.append(f"{memory_id}: not admissible now ({current.lifecycle_state.value})")
            elif version is not None and current.version != version:
                problems.append(f"{memory_id}: revised since (v{version} -> v{current.version})")
        items.append({**item, "admissible_now": not problems, "changes": problems})
    return {**r, "selected": items}
