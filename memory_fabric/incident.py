"""Incident reconstruction: from an action back to its sources (plan R2, Task 9).

Given an `ActionGated` record, this traces the path the plan names: the action,
the evidence it was certified on, what that evidence was derived from, down to
source observations and the agents who wrote them, together with the retrievals
that exposed the evidence to the acting agent and what was withdrawn after.

Three rules govern the report:

- **Redacted.** Ids, versions, agents, reason codes and log positions only.
  Never memory content. The replay that builds it leaves content sealed.
- **As of the action.** State is replayed from the log up to the action's
  position, so a later withdrawal shows up under "found later" and does not
  rewrite what the evidence looked like when it was used.
- **Dependency is not causation.** Every source on the path is reported as a
  dependency. A separate counterfactual asks whether the evidence would still
  have been supported had that source been withdrawn at the time of the action.
  It is a property of the recorded justification structure, evaluated in a
  read-only replay that never touches the store. It is labelled as that and
  never as "the cause". `experiments/p9_incidents.py` measures how often it
  agrees with actually withdrawing the source in a live replica.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

from . import events as ev
from .justification import JustificationKind
from .model import LifecycleState
from .projections import Projection

MAX_NODES = 2_000
"""Bounds the trace on a pathological graph (S9)."""

CAVEAT = ("Paths are recorded dependencies, not proof of causation. "
          "'necessary' means the evidence would not have been supported had this "
          "source been withdrawn at the time of the action, under the recorded "
          "justification structure. It does not mean the source caused the outcome.")


@dataclass(frozen=True)
class Node:
    memory_id: str
    version: int
    writer: str
    lifecycle_at_action: str
    role: str  # evidence | premise | source
    kind_from_child: str = ""


@dataclass(frozen=True)
class SourceFinding:
    memory_id: str
    writer: str
    necessary: bool
    """Counterfactual: would withdrawing this source have left the evidence
    unsupported? A dependency property, not a causal finding."""


@dataclass
class IncidentReport:
    action_seq: int
    tool: str
    agent_id: str
    allowed: bool
    reason_codes: tuple[str, ...]
    evidence: tuple[tuple[str, int], ...]
    nodes: list[Node] = field(default_factory=list)
    edges: list[tuple[str, str, str]] = field(default_factory=list)
    sources: list[SourceFinding] = field(default_factory=list)
    exposures: list[dict[str, Any]] = field(default_factory=list)
    found_later: list[dict[str, Any]] = field(default_factory=list)
    truncated: bool = False
    caveat: str = CAVEAT

    def to_json(self) -> dict[str, Any]:
        return {
            "action_seq": self.action_seq, "tool": self.tool, "agent_id": self.agent_id,
            "allowed": self.allowed, "reason_codes": list(self.reason_codes),
            "evidence": [list(e) for e in self.evidence],
            "nodes": [n.__dict__ for n in self.nodes],
            "edges": [list(e) for e in self.edges],
            "sources": [s.__dict__ for s in self.sources],
            "exposures": self.exposures, "found_later": self.found_later,
            "truncated": self.truncated, "caveat": self.caveat,
        }


def _kind(state: Any, child: str, parent: str) -> JustificationKind:
    memory = state.memories.get(child)
    raw = ((memory.context.get("justifications") or {}) if memory else {}).get(parent)
    try:
        return JustificationKind(str(raw)) if raw is not None else JustificationKind.REQUIRED
    except ValueError:
        return JustificationKind.REQUIRED


def _ancestors(state: Any, memory_id: str) -> set[str]:
    out: set[str] = set()
    frontier = list(state.parents.get(memory_id, ()))
    while frontier:
        m = frontier.pop()
        if m not in out:
            out.add(m)
            frontier.extend(state.parents.get(m, ()))
    return out


def _independent(state: Any, a: str, b: str) -> bool:
    """`LineageGraph.evidence_is_independent` for two memories: no shared
    ancestor, counting each memory as its own ancestor."""
    return not ((_ancestors(state, a) | {a}) & (_ancestors(state, b) | {b}))


def _copy_component(state: Any, memory_id: str) -> set[str]:
    """Every memory that is the same document, walked in both directions."""
    out, frontier = {memory_id}, [memory_id]
    while frontier:
        m = frontier.pop()
        nxt = set(state.copies.get(m, ()))
        if m in state.copy_of:
            nxt.add(state.copy_of[m])
        for other in nxt - out:
            out.add(other)
            frontier.append(other)
    return out - {memory_id}


def supported(state: Any, memory_id: str, lost: frozenset[str],
              _memo: dict[str, bool] | None = None) -> bool:
    """Would `memory_id` be supported if every memory in `lost` were withdrawn?

    Read-only, over a projection, and mirroring `JustificationGraph.recompute`
    rule for rule. Every REQUIRED premise must hold. When there are none,
    at least one ALTERNATIVE must hold that is independent of the others and
    of what was lost. A COPIED premise carries no support of its own. A memory
    falls with any withdrawn member of its copy component. The first version
    treated COPIED as required and ignored independence, and P9 measured 20%
    false attribution against live withdrawal before it was corrected.
    """
    memo = {} if _memo is None else _memo
    if memory_id in memo:
        return memo[memory_id]
    memo[memory_id] = False  # cycle guard: a cycle supports nothing
    memory = state.memories.get(memory_id)
    if memory is None or memory_id in lost \
            or memory.lifecycle_state is not LifecycleState.ACTIVE:
        return False
    if any(c in lost or (c in state.memories and
                         state.memories[c].lifecycle_state is not LifecycleState.ACTIVE
                         and state.memories[c].lifecycle_state.value in
                         ("quarantined", "deprecated", "deleted"))
           for c in _copy_component(state, memory_id)):
        return False
    parents = sorted(state.parents.get(memory_id, ()))
    if not parents:
        memo[memory_id] = True
        return True
    required_total = required_ok = 0
    alternatives: list[str] = []
    lost_parents: list[str] = []
    for parent in parents:
        kind = _kind(state, memory_id, parent)
        if kind is JustificationKind.CONTRADICTS:
            continue
        if kind is JustificationKind.REQUIRED:
            required_total += 1
        recorded = state.parent_versions.get((memory_id, parent))
        current = state.memories.get(parent)
        moved = current is not None and recorded is not None and current.version != recorded
        if supported(state, parent, lost, memo) and not moved:
            if kind is JustificationKind.REQUIRED:
                required_ok += 1
            elif kind is JustificationKind.ALTERNATIVE:
                alternatives.append(parent)
        else:
            lost_parents.append(parent)
    kept: list[str] = []
    for candidate in sorted(alternatives):
        if any(not _independent(state, candidate, gone) for gone in lost_parents):
            continue
        if all(_independent(state, candidate, other) for other in kept):
            kept.append(candidate)
    ok = required_ok == required_total and (required_total > 0 or bool(kept))
    memo[memory_id] = ok
    return ok


def replay_until(fabric: Any, seq: int) -> Any:
    """Projection state as of log position `seq`. Content stays sealed."""
    projection = Projection()
    projection.apply_all(e for e in fabric.log.read() if e.seq is not None and e.seq <= seq)
    return projection.state


def action_events(fabric: Any, tool: str | None = None,
                  agent_id: str | None = None) -> list[Any]:
    return [e for e in fabric.log.read_types([ev.EventType.ACTION_GATED])
            if (tool is None or e.payload.get("tool") == tool)
            and (agent_id is None or e.agent_id == agent_id)]


def reconstruct(fabric: Any, action_seq: int | None = None) -> IncidentReport:
    """Report on one gated action, the latest one if `action_seq` is None."""
    actions = action_events(fabric)
    if not actions:
        raise LookupError("no gated action in this store")
    action = actions[-1] if action_seq is None else next(
        (a for a in actions if a.seq == action_seq), None)
    if action is None:
        raise LookupError(f"no gated action at seq {action_seq}")
    p = action.payload
    evidence = tuple((str(m), int(v)) for m, v in p.get("evidence") or [])
    report = IncidentReport(
        action_seq=int(action.seq), tool=str(p.get("tool")), agent_id=str(action.agent_id),
        allowed=bool(p.get("allowed")), reason_codes=tuple(p.get("reason_codes") or ()),
        evidence=evidence)
    state = replay_until(fabric, int(action.seq))

    # Walk evidence -> premises -> sources, breadth first, bounded.
    seen: set[str] = set()
    frontier = [(m, "evidence", "") for m, _ in evidence]
    sources: list[str] = []
    while frontier:
        memory_id, role, kind = frontier.pop(0)
        if memory_id in seen:
            continue
        if len(seen) >= MAX_NODES:
            report.truncated = True
            break
        seen.add(memory_id)
        memory = state.memories.get(memory_id)
        parents = sorted(state.parents.get(memory_id, ()))
        original = state.copy_of.get(memory_id)
        is_source = not parents and original is None
        report.nodes.append(Node(
            memory_id, memory.version if memory else 0,
            memory.provenance.created_by if memory else "",
            memory.lifecycle_state.value if memory else "missing",
            "source" if is_source and role != "evidence" else role, kind))
        if is_source:
            sources.append(memory_id)
        for parent in parents:
            k = _kind(state, memory_id, parent).value
            report.edges.append((memory_id, parent, k))
            frontier.append((parent, "premise", k))
        if original is not None:
            report.edges.append((memory_id, original, "copy_of"))
            frontier.append((original, "premise", "copy_of"))

    # Counterfactual per source: withdraw it alone, in the replay, and ask
    # whether every piece of evidence would still be supported.
    for source in sorted(set(sources)):
        lost = frozenset({source})
        still = all(supported(state, m, lost) for m, _ in evidence)
        writer = state.memories[source].provenance.created_by if source in state.memories else ""
        report.sources.append(SourceFinding(source, writer, necessary=not still))

    # Retrievals that exposed path members to the acting agent before the action.
    path = {n.memory_id for n in report.nodes}
    for e in fabric.log.read_types([ev.EventType.EXPOSURE_DECIDED]):
        if e.seq is not None and e.seq < action.seq and e.agent_id == action.agent_id \
                and e.payload.get("memory_id") in path and e.payload.get("exposed"):
            report.exposures.append({"seq": e.seq, "memory_id": e.payload["memory_id"],
                                     "version": e.payload.get("version"),
                                     "episode_id": e.episode_id})
    # What was withdrawn on the path after the action.
    for e in fabric.log.read_types([ev.EventType.LIFECYCLE_CHANGED]):
        if e.seq is not None and e.seq > action.seq and e.payload.get("memory_id") in path:
            report.found_later.append({
                "seq": e.seq, "memory_id": e.payload["memory_id"],
                "to": e.payload.get("to_state") or e.payload.get("to"),
                "basis": e.payload.get("basis"), "actor": e.agent_id or e.payload.get("actor")})
    return report


def responsible_sources(report: IncidentReport) -> list[str]:
    """Sources whose withdrawal would have left the evidence unsupported."""
    return [s.memory_id for s in report.sources if s.necessary]


def _redaction_check(report: IncidentReport, contents: Iterable[str]) -> bool:
    """True if no content string appears in the report. For tests."""
    import json

    dump = json.dumps(report.to_json(), default=str)
    return not any(c and c in dump for c in contents)


__all__ = [
    "IncidentReport", "Node", "SourceFinding", "reconstruct", "replay_until",
    "supported", "responsible_sources", "CAVEAT",
]
