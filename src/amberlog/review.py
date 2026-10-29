"""The review queue: what is waiting for a person, and the four decisions.

New memories start as private candidates. Nothing an agent writes reaches
retrieval until someone validates it, and nothing reaches the agent's
teammates until someone shares it (scope is enforced on reads). This module is
the inbox for that work, and the one place its decisions are made, so the CLI
and the dashboard cannot drift apart on what "approve" means.

| decision | what it does | who can read it after |
|---|---|---|
| **approve** | validate, then share to `team` | every agent in the tenant |
| **limit** | validate only | the agent that wrote it |
| **correct** | revise the text, then approve | every agent in the tenant |
| **reject** | deprecate, with the reason | nobody; the record stays |

Every decision names its reviewer, and the reviewer is the `actor` on each
event it writes, so `audit` and the status label "reviewed" show who decided.

The queue also lists memories an ingest screen quarantined (a secret or an
injection pattern). Approving one of those needs `override_screen=True`: a
false positive can be released deliberately, never by accident.
"""

from __future__ import annotations

__stability__ = "beta"

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from .model import LifecycleState, Memory, Scope, WithdrawalBasis

if TYPE_CHECKING:  # pragma: no cover
    from .fabric import Amberlog

DECISIONS = ("approve", "limit", "correct", "reject")


class ReviewError(ValueError):
    """A decision the memory's state does not allow."""


@dataclass
class ReviewItem:
    memory_id: str
    kind: str
    """`candidate`, or `screened` for a memory an ingest screen quarantined."""
    author: str
    created_at: int
    content: str
    """Safe to display: detected secrets are redacted, as everywhere else."""
    reason: str
    commands: dict[str, str] = field(default_factory=dict)

    def to_json(self) -> dict[str, Any]:
        return dict(self.__dict__)


def _screened(fabric: "Amberlog", memory: Memory) -> bool:
    return (memory.lifecycle_state is LifecycleState.QUARANTINED
            and fabric.state.withdrawal_basis.get(memory.id) == WithdrawalBasis.SENSITIVE_DATA.value)


def queue(fabric: "Amberlog", tenant: str | None = None) -> list[ReviewItem]:
    """Candidates and screen quarantines, oldest first."""
    from .observability.report import safe_content

    items = []
    for memory in fabric.state.memories.values():
        if tenant is not None and memory.tenant_id != tenant:
            continue
        if memory.lifecycle_state is LifecycleState.CANDIDATE:
            kind, reason = "candidate", "new, not yet reviewed"
        elif _screened(fabric, memory):
            kind, reason = "screened", "quarantined by an ingest screen; approving needs --override-screen"
        else:
            continue
        base = f"amberlog --db <store> review {memory.id} --actor <you>"
        commands = {
            "approve": f"{base} --approve" + (" --override-screen" if kind == "screened" else ""),
            "limit": f"{base} --limit",
            "correct": f'{base} --correct "<corrected text>"',
            "reject": f'{base} --reject --reason "<why>"',
        }
        items.append(ReviewItem(memory.id, kind, memory.provenance.created_by,
                                memory.created_at or 0, safe_content(fabric, memory.content)[0],
                                reason, commands))
    items.sort(key=lambda i: (i.created_at, i.memory_id))
    return items


def decide(fabric: "Amberlog", memory_id: str, decision: str, reviewer: str,
           reason: str = "", correction: str | None = None,
           override_screen: bool = False) -> dict[str, Any]:
    """Apply one decision. Returns what happened, including a refused share."""
    if decision not in DECISIONS:
        raise ReviewError(f"decision must be one of {', '.join(DECISIONS)}")
    if not reviewer or reviewer == "operator":
        raise ReviewError("name the reviewer: a decision without one cannot be audited")
    memory = fabric.state.memories.get(memory_id)
    if memory is None:
        raise ReviewError(f"no memory {memory_id}")
    screened = _screened(fabric, memory)
    if memory.lifecycle_state is not LifecycleState.CANDIDATE and not screened:
        raise ReviewError(f"{memory_id} is {memory.lifecycle_state.value}, not waiting for review")

    if decision == "reject":
        if not reason:
            raise ReviewError("a rejection needs a reason")
        fabric.forget(memory_id, reason=f"rejected in review: {reason}", actor=reviewer)
        return {"decision": "reject", "state": "deprecated", "scope": memory.scope.value}

    if screened:
        if not override_screen:
            raise ReviewError("an ingest screen quarantined this; pass override_screen "
                              "to release it deliberately")
        fabric.release(memory_id, actor=reviewer, reason=reason or "screen finding overridden in review")
    if decision == "correct":
        if not correction:
            raise ReviewError("a correction needs the corrected text")
        fabric.revise(memory_id, correction, agent_id=reviewer,
                      reason=reason or "corrected in review")
        if fabric.state.memories[memory_id].lifecycle_state is LifecycleState.QUARANTINED:
            # The corrected text tripped a screen itself; it stays quarantined.
            return {"decision": "correct", "state": "quarantined", "scope": memory.scope.value,
                    "note": "the corrected text was quarantined by an ingest screen"}
    if fabric.state.memories[memory_id].lifecycle_state is not LifecycleState.ACTIVE:
        fabric.validate(memory_id, actor=reviewer, reason=reason or f"{decision} in review")
    result: dict[str, Any] = {"decision": decision, "state": "active"}
    if decision in ("approve", "correct"):
        ruling = fabric.share(memory_id, Scope.TEAM, actor=reviewer)
        result["scope"] = fabric.state.memories[memory_id].scope.value
        if not ruling.permits_sharing:
            result["note"] = "active, but sharing to the team was refused: " + "; ".join(ruling.reasons)
    else:
        result["scope"] = fabric.state.memories[memory_id].scope.value
    return result
