"""Which decisions genuinely depended on a corrected memory?

`influence.impact` answers "what is downstream of this memory": every
memory derived from it, every agent it was shown to, and every action whose
evidence it reached. That is the complete list, and the right one to start
from, but it is noisy. An action certified on two independent sources
would have been allowed without either one, and putting it in the review
queue wastes the reviewer's attention.

`decisions_depending_on` asks a counterfactual of the product's own
verifier. For each logged gate decision (`ActionGated`) that the corrected
memory's reach touches, it takes the evidence the decision recorded, drops
everything in reach (the memory, its copies, everything derived from it),
re-certifies what remains under the same `min_independent_sources`, and
verifies that certificate against the store as it is now:

| verdict | meaning |
|---|---|
| `depended` | without the corrected memory and its reach, the remaining evidence does not satisfy the decision's own policy: review it |
| `would_stand` | independent evidence remains that the verifier accepts: the decision did not hinge on the corrected memory |
| `exposed_only` | agents that were shown something in reach without any recorded action resting on it |

**What it means, stated.** "Depended" means the *recorded evidence* would no
longer meet the *recorded policy*. It does not mean the agent's reasoning
used the memory. Establishing that needs replaying the agent without it,
which `replay`, a caller-supplied callable, can add per decision. Independence
is judged by source roots (`certificates.py`), with the limits measured in
S2: a laundered copy that looks independent counts as independent.
"""

from __future__ import annotations

__stability__ = "beta"

from typing import TYPE_CHECKING, Any, Callable

from . import events as ev
from .influence import downstream, edges

if TYPE_CHECKING:  # pragma: no cover
    from .fabric import MemoryFabric

DEPENDED = "depended"
WOULD_STAND = "would_stand"


def decisions_depending_on(fabric: "MemoryFabric", memory_id: str,
                           replay: Callable[[dict[str, Any], list[str]], bool] | None = None
                           ) -> dict[str, Any]:
    """Classify every allowed action whose evidence the memory's reach touches.

    `replay(decision, remaining_evidence) -> still_same` may override a
    `would_stand` verdict with a real counterfactual (re-asking the agent
    without the memory). It is consulted only for decisions the evidence
    check says would stand.
    """
    graph = list(edges(fabric))
    reach = {memory_id} | downstream(fabric, memory_id, graph)
    depended: list[dict[str, Any]] = []
    would_stand: list[dict[str, Any]] = []
    touched_agents: set[str] = set()
    for event in fabric.log.read_types([ev.EventType.ACTION_GATED]):
        p = event.payload
        if not p.get("allowed"):
            continue
        evidence = [str(e[0]) for e in p.get("evidence", [])]
        hit = [e for e in evidence if e in reach]
        if not hit:
            continue
        remaining = [e for e in evidence if e not in reach and e in fabric.state.memories]
        need = max(1, int(p.get("min_independent_sources") or 1))
        agent = str(event.agent_id or "")
        record = {"seq": event.seq, "tool": p.get("tool"), "agent_id": agent,
                  "claim_id": p.get("claim_id"), "in_reach": hit, "remaining": remaining}
        stands = False
        if remaining:
            cert = fabric.certify(f"counterfactual:{p.get('claim_id')}", remaining,
                                  agent or "counterfactual", tenant_id=p.get("tenant_id"),
                                  min_independent_sources=need)
            check = fabric.verify_certificate(cert, agent or "counterfactual")
            stands = bool(check.ok)
            record["counterfactual"] = list(check.reason_codes)
        if stands and replay is not None:
            stands = bool(replay(record, remaining))
            record["replayed"] = True
        (would_stand if stands else depended).append(record)
        touched_agents.add(agent)
    exposed = sorted({e.target for e in graph if e.type == "exposed_to" and e.source in reach
                      and e.target.startswith("agent:")}
                     - {f"agent:{a}" for a in touched_agents})
    return {"memory_id": memory_id, "reach": sorted(reach),
            DEPENDED: depended, WOULD_STAND: would_stand, "exposed_only": exposed}
