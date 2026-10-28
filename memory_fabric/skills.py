"""Governed procedural skills: reusable steps that cannot outlive their premises or widen permissions.

A skill is a procedural memory: a trigger, ordered steps, the tools it uses,
the checks that show it works, and the memories it rests on (prerequisites).
It is stored as a derivation of those prerequisites, so the store's ordinary
machinery applies to it:

- **It cannot outlive what it rests on.** Withdraw a prerequisite and the skill
  is contested by the same propagation that contests any conclusion; `runnable`
  refuses it.
- **Proposed is not approved.** A skill lands as a candidate. `approve` requires
  a reviewer other than its author and a passing result for every declared check.
- **It grants nothing.** The tools a skill names are not permissions. `runnable`
  checks each against the action policy's grants for the agent that would run
  it; a skill naming a tool the agent lacks is refused, never escalated.
- **Every version is approved.** `revise` writes the new steps as a *new*
  candidate skill that supersedes the old one; the old version keeps running
  until the new one is approved, and is retired (deprecated) at that moment.
  `rollback` proposes an earlier version's steps again, under the same rule.

Nothing here executes a step: running the tools is the caller's, through
`ActionGate.execute`, which re-verifies evidence at the moment of the action.

    from memory_fabric import skills
    sid = skills.propose(fabric, "agent-a", "rotate-gate-code", trigger="gate code older than 30 days",
                         steps=["read current code", "issue new code", "notify security"],
                         tools=["issue_gate_code"], checks=["new code differs from old"],
                         prerequisites=[policy_memory_id])
    skills.approve(fabric, sid, reviewer="lead", results={"new code differs from old": True})
    skills.runnable(fabric, sid, "agent-b", policy=gate.policy)   # Verdict(ok=..., reasons=[...])
"""

from __future__ import annotations

__stability__ = "experimental"

import json
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Mapping, Sequence

if TYPE_CHECKING:  # pragma: no cover
    from .fabric import MemoryFabric

KIND = "skill"


@dataclass
class Verdict:
    ok: bool
    reasons: list[str] = field(default_factory=list)


def _render(name: str, trigger: str, steps: Sequence[str], version: int = 1) -> str:
    # The version is in the text: a rollback re-proposes an old version's steps on
    # purpose, and must not read as re-ingesting the retired version it copies.
    return (f"Skill {name} (version {version}, rev{version:03d}): when {trigger}: "
            + "; ".join(f"{i}. {s}" for i, s in enumerate(steps, 1)))


def spec(fabric: "MemoryFabric", skill_id: str) -> dict[str, Any]:
    m = fabric.get(skill_id)
    s = (m.context or {}).get(KIND)
    if not isinstance(s, Mapping):
        raise ValueError(f"{skill_id} is not a skill")
    return dict(s)


def propose(fabric: "MemoryFabric", agent_id: str, name: str, trigger: str, steps: Sequence[str],
            tools: Sequence[str] = (), checks: Sequence[str] = (), prerequisites: Sequence[str] = (),
            scope: str = "team", tenant_id: str | None = None, supersedes: str | None = None) -> str:
    """Write a skill as a candidate derived from its prerequisites. Returns its memory id."""
    if not steps:
        raise ValueError("a skill needs at least one step")
    version = len(history(fabric, supersedes)) + 1 if supersedes else 1
    body = {"name": name, "trigger": trigger, "steps": list(steps), "tools": sorted(set(tools)),
            "checks": list(checks), "author": agent_id, "prerequisites": list(prerequisites),
            "supersedes": supersedes, "version": version}
    from .model import MemoryType

    kwargs: dict[str, Any] = {"tenant_id": tenant_id} if tenant_id else {}
    if prerequisites:
        return fabric.derive(agent_id, _render(name, trigger, steps, version), parents=list(prerequisites),
                             type=MemoryType.PROCEDURAL, context={KIND: body}, scope=scope,
                             auto_activate=False, **kwargs)
    return fabric.remember(agent_id, _render(name, trigger, steps, version), type=MemoryType.PROCEDURAL,
                           context={KIND: body}, scope=scope, auto_activate=False, **kwargs)


def approve(fabric: "MemoryFabric", skill_id: str, reviewer: str, results: Mapping[str, bool]) -> None:
    """Activate a skill: a reviewer other than its author, and every declared check passed."""
    s = spec(fabric, skill_id)
    if reviewer == s["author"]:
        raise PermissionError("a skill's author cannot approve it")
    failed = [c for c in s["checks"] if results.get(c) is not True]
    if failed:
        raise ValueError(f"checks not passed: {failed}")
    fabric.validate(skill_id, actor=reviewer,
                    reason="skill approved; checks passed: " + json.dumps(sorted(results)))
    old = s.get("supersedes")
    if old and fabric.state.memories.get(old) is not None:
        fabric.forget(old, reason=f"superseded by approved skill version {skill_id}", actor=reviewer)


def runnable(fabric: "MemoryFabric", skill_id: str, agent_id: str, policy: Any = None) -> Verdict:
    """Whether `agent_id` may follow this skill now. Says why not; executes nothing."""
    from .model import EXPOSABLE_STATES, LifecycleState

    m = fabric.get(skill_id)
    s = spec(fabric, skill_id)
    reasons = []
    if m.lifecycle_state is not LifecycleState.ACTIVE:
        reasons.append(f"skill is {m.lifecycle_state.value}, not approved and active")
    for parent in getattr(m.provenance, "parents", ()) or ():
        pid = parent[0] if isinstance(parent, (tuple, list)) else getattr(parent, "memory_id", parent)
        pm = fabric.state.memories.get(pid)
        if pm is None or pm.lifecycle_state not in EXPOSABLE_STATES:
            reasons.append(f"prerequisite {pid} is {pm.lifecycle_state.value if pm else 'missing'}")
    if s["tools"]:
        granted = set((getattr(policy, "grants", {}) or {}).get(agent_id, ())) if policy is not None else set()
        missing = [t for t in s["tools"] if t not in granted]
        if missing:
            reasons.append(f"agent {agent_id} is not granted {missing}; a skill confers no permission")
    return Verdict(ok=not reasons, reasons=reasons)


def revise(fabric: "MemoryFabric", skill_id: str, agent_id: str, steps: Sequence[str],
           tools: Sequence[str] | None = None, checks: Sequence[str] | None = None) -> str:
    """Propose new steps as a new candidate version. The old version runs until this one is approved."""
    s = spec(fabric, skill_id)
    m = fabric.get(skill_id)
    return propose(fabric, agent_id, s["name"], s["trigger"], steps,
                   tools=s["tools"] if tools is None else tools,
                   checks=s["checks"] if checks is None else checks,
                   prerequisites=s.get("prerequisites", []), scope=m.scope.value,
                   tenant_id=m.tenant_id, supersedes=skill_id)


def history(fabric: "MemoryFabric", skill_id: str) -> list[str]:
    """This version and every one it superseded, newest first."""
    chain, seen = [], set()
    current: str | None = skill_id
    while current and current not in seen and current in fabric.state.memories:
        seen.add(current)
        chain.append(current)
        current = spec(fabric, current).get("supersedes")
    return chain


def rollback(fabric: "MemoryFabric", skill_id: str, agent_id: str, to: str) -> str:
    """Propose an earlier version's steps again, superseding `skill_id`. Needs approval like any version."""
    if to not in history(fabric, skill_id):
        raise ValueError(f"{to} is not an earlier version of {skill_id}")
    old = spec(fabric, to)
    return revise(fabric, skill_id, agent_id, old["steps"], tools=old["tools"], checks=old["checks"])
