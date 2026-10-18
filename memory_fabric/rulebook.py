"""A reflective rulebook: an agent's own rules, revised from outcomes, adopted only on evidence.

M2 (`research/prereg/m2-reflective-rulebooks.md`), requested 2026-10-18 as
"memory-based recursive self-improvement through reflective rulebooks".

An agent that reflects on its failures and rewrites its own rules can get
better. It can also get worse, confidently: a reflection is a hypothesis, and
an agent that adopts every hypothesis it writes has no way to notice the one
that hurt. "Self-improvement" that is self-assessed is the value/relevance
confusion again (AGENTS.md principle 1), with the agent as its own judge.

So the rulebook keeps the two steps apart:

- **propose**: a reflection becomes a *candidate* memory. It holds the
  proposed rules (a `MemoryObjective`, validated against the store's
  fields), the rationale, and a parent edge to the revision it would replace.
  Candidates are not active, so nothing retrieves or applies them.
- **adopt**: the candidate replaces the current rules only when evidence the
  agent did not produce says it is better. That evidence is accuracy on
  held-out tasks with verified outcomes, with the candidate's score above the
  incumbent's by at least `margin`. The decision and its numbers are written
  into the revision's reason, so the log says *why* every rule is there.
  A rejected candidate is deprecated, not deleted.

The current rulebook is one memory whose versions are its history
(`MemoryFabric.revise`).

**What a rule can do is bounded by construction.** Rules are objectives:
filters over fields the store already has, applied *after* the eligibility
chokepoint (tenant, scope, lifecycle). They can only narrow what an agent
sees. They cannot grant a tool, widen a scope or admit a withdrawn memory,
because none of those is expressible in a rule.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from .model import LifecycleState
from .objective import MemoryObjective

if TYPE_CHECKING:  # pragma: no cover
    from .fabric import MemoryFabric

KIND = "rulebook"


@dataclass(frozen=True)
class Decision:
    adopted: bool
    candidate_id: str
    incumbent_score: float
    candidate_score: float
    n: int
    reason: str


class Rulebook:
    def __init__(self, fabric: "MemoryFabric", name: str, agent_id: str,
                 statement: str = "") -> None:
        self.fabric, self.name, self.agent_id = fabric, name, agent_id
        existing = [m for m in fabric.state.memories.values()
                    if m.context.get(KIND) == name and m.context.get("role") == "current"]
        if existing:
            self.memory_id = existing[0].id
        else:
            empty = MemoryObjective(statement)
            self.memory_id = fabric.remember(
                agent_id, json.dumps(empty.to_json(), sort_keys=True), scope="private",
                context={KIND: name, "role": "current"}, auto_activate=True)

    def current(self) -> MemoryObjective:
        return MemoryObjective.from_json(json.loads(self.fabric.get(self.memory_id).content))

    @property
    def version(self) -> int:
        return self.fabric.get(self.memory_id).version

    def propose(self, objective: MemoryObjective, rationale: str) -> str:
        """Store a reflection's proposed rules as a candidate. Nothing applies it yet."""
        return self.fabric.derive(
            self.agent_id, json.dumps(objective.to_json(), sort_keys=True),
            parents=[self.memory_id], scope="private",
            context={KIND: self.name, "role": "proposal", "rationale": rationale[:500],
                     "against_version": self.version}, auto_activate=False)

    def candidate(self, candidate_id: str) -> MemoryObjective:
        return MemoryObjective.from_json(json.loads(self.fabric.get(candidate_id).content))

    def adopt(self, candidate_id: str, *, incumbent_score: float, candidate_score: float,
              n: int, margin: float = 0.0, verifier: str) -> Decision:
        """Adopt the candidate if held-out, verified scores say it is better."""
        if verifier == self.agent_id:
            raise ValueError("the agent that proposed the rules may not verify them")
        better = candidate_score > incumbent_score + margin
        reason = (f"{'adopted' if better else 'rejected'}: held-out accuracy "
                  f"{candidate_score:.3f} against {incumbent_score:.3f} (n={n}, "
                  f"margin {margin}), verified by {verifier}")
        if better:
            self.fabric.revise(self.memory_id, self.fabric.get(candidate_id).content,
                               agent_id=self.agent_id, reason=reason)
        # Decided either way: an adopted candidate now lives on as the current
        # version, a rejected one stays in the log with the reason.
        if self.fabric.get(candidate_id).lifecycle_state is not LifecycleState.DEPRECATED:
            self.fabric.forget(candidate_id, reason=reason, actor=verifier)
        return Decision(better, candidate_id, incumbent_score, candidate_score, n, reason)

    def history(self) -> list[dict[str, Any]]:
        """Every adopted version, oldest first."""
        versions = self.fabric.state.history.get(self.memory_id, [])
        out = [{"version": v.version, "rules": json.loads(v.content)} for v in versions]
        now = self.fabric.get(self.memory_id)
        out.append({"version": now.version, "rules": json.loads(now.content)})
        return out
