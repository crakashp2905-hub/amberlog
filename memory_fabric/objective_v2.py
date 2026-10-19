"""MemoryObjectiveV2: a session's purpose, with hard limits kept apart from preferences.

V1 (`objective.py`, M1) is a single filter: include groups and exclusions,
all equally hard. M1 measured it helps, and found the failure that motivates
this version. A compiled exclusion is as hard as a reviewed one, so a model
that misread "ignore other plants" could filter out the one memory saying a
valve is unsafe everywhere.

**Eligibility and ranking are different steps:**

    eligible = SecurityAllowed ∧ LifecycleAllowed ∧ hard scope ∧ not hard-excluded
    then rank by relevance × evidence

The store enforces security (tenant, scope, security class) and lifecycle
before an objective is consulted. Nothing here can widen them. The objective
narrows only through **hard** rules. **Soft** rules move a memory up or down.
**Uncertain** rules (a compiler's guess nobody reviewed) are reported and
weigh lightly; they never filter.

**Safety evidence is not filtered without a check.** A memory that matches a
`safety_constraints` rule, or whose context says `safety: true`, stays
eligible when an *unreviewed* hard rule would exclude it. The exemption is
recorded in `explain()`. Only a human-reviewed objective (`reviewed_by`) can
exclude safety evidence, and that is recorded too.

**Irrelevant is not safe to delete.** An objective changes what one session
is shown. It has no write path: it cannot deprecate, delete or demote a
memory. Excluding a memory for a session says nothing about it outside that
session.

**Evidence-aware satisfaction** (`evidence_score`), each in [0, 1]:

- provenance and authority: `authority.py` trust;
- version and date: current version, valid at the session's `as_of`, fresh
  within `freshness_ms`;
- observation vs inference: an observation outranks a derived claim; an
  instruction is never evidence;
- independence: the second memory from one source root counts for less;
- answers the question: the retrieval relevance itself.

**Adaptive but not self-authorising.** `ObjectiveLog.propose` records a
change with its evaluation; `adopt` needs a reviewer who is not the proposer
and an evaluation that did not get worse on its own terms. Every step is in
the store's event log.
"""

from __future__ import annotations

__stability__ = "experimental"

import hashlib
import json
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Any, Mapping, Sequence

from .objective import Rule

if TYPE_CHECKING:  # pragma: no cover
    from .fabric import MemoryFabric

STRENGTHS = ("hard", "soft", "uncertain")
UNCERTAINTY_POLICIES = ("surface", "abstain", "prefer_confident")
IMPACTS = ("low", "high")


@dataclass(frozen=True)
class Constraint:
    rule: Rule
    strength: str = "hard"
    weight: float = 0.5
    """For soft and uncertain rules: how far a match moves the score."""

    def __post_init__(self) -> None:
        if self.strength not in STRENGTHS:
            raise ValueError(f"strength must be one of {STRENGTHS}")

    def to_json(self) -> dict[str, Any]:
        return {**self.rule.to_json(), "strength": self.strength, "weight": self.weight}

    @classmethod
    def from_json(cls, d: Mapping[str, Any]) -> "Constraint":
        return cls(Rule(d["field"], d["op"], d["value"]), str(d.get("strength", "hard")),
                   float(d.get("weight", 0.5)))


@dataclass(frozen=True)
class MemoryObjectiveV2:
    goal: str
    required_facts: tuple[str, ...] = ()
    """Claims the session needs covered. Reported as omissions when nothing
    eligible mentions them; never used to filter."""
    preferred_evidence: tuple[Constraint, ...] = ()
    """Soft by default: what good evidence looks like here."""
    excluded_context: tuple[Constraint, ...] = ()
    """Hard or soft exclusions. Hard ones filter, subject to the safety rule."""
    safety_constraints: tuple[Rule, ...] = ()
    """Memories matching any of these are safety evidence."""
    scope: tuple[tuple[Rule, ...], ...] = ()
    """Hard inclusion, an OR of AND-groups, as V1's `include`."""
    as_of: int | None = None
    freshness_ms: int | None = None
    uncertainty_policy: str = "surface"
    decision_impact: str = "low"
    """`high`: rank refuses evidence below `unverified` authority, and
    surfaces conflicts rather than resolving them."""
    compiled_by: str | None = None
    reviewed_by: str | None = None
    include_history: bool = False
    """Show memories whose validity has ended. Off: a session asks what is
    true now unless it says otherwise. M1b's dev pilot found a 3B model picks
    an expired memory over the current one even when it is marked "validity
    ended", once a hard filter has made room for it in the top k."""

    def __post_init__(self) -> None:
        if self.uncertainty_policy not in UNCERTAINTY_POLICIES:
            raise ValueError(f"uncertainty_policy must be one of {UNCERTAINTY_POLICIES}")
        if self.decision_impact not in IMPACTS:
            raise ValueError(f"decision_impact must be one of {IMPACTS}")

    # --- eligibility -----------------------------------------------------

    def is_safety(self, context: Mapping[str, Any]) -> bool:
        return bool(context.get("safety")) or any(r.holds(context) for r in self.safety_constraints)

    def eligibility(self, context: Mapping[str, Any]) -> tuple[bool, str]:
        """Whether the objective admits a memory, and why, before ranking."""
        in_scope = not self.scope or any(all(r.holds(context) for r in g) for g in self.scope)
        excluded_by = next((c for c in self.excluded_context
                            if c.strength == "hard" and c.rule.holds(context)), None)
        if in_scope and excluded_by is None:
            return True, "in scope"
        reason = ("outside scope" if not in_scope
                  else f"hard exclusion {excluded_by.rule.field} {excluded_by.rule.op} "
                       f"{excluded_by.rule.value!r}")
        if self.is_safety(context):
            if self.reviewed_by:
                return False, f"{reason}; safety evidence excluded by reviewed objective " \
                              f"({self.reviewed_by})"
            return True, f"kept: safety evidence; an unreviewed objective would have excluded " \
                         f"it ({reason})"
        return False, reason

    def admits(self, context: Mapping[str, Any]) -> bool:
        return self.eligibility(context)[0]

    # --- ranking ---------------------------------------------------------

    def evidence_score(self, fabric: "MemoryFabric", memory_id: str, relevance: float,
                       seen_roots: dict[str, int]) -> tuple[float, dict[str, float]]:
        from . import authority

        memory = fabric.state.memories[memory_id]
        found = authority.of(fabric, memory_id)
        parts: dict[str, float] = {"relevance": float(relevance)}
        parts["authority"] = {authority.ELEVATED: 1.0, authority.UNVERIFIED: 0.8,
                              authority.UNTRUSTED: 0.3}[found.trust]
        if found.kind == "instruction":
            parts["authority"] = 0.0
        parts["kind"] = {"observation": 1.0, "derived_claim": 0.8, "instruction": 0.0}[found.kind]
        fresh = 1.0
        if self.freshness_ms is not None:
            age = fabric.now() - int(memory.created_at or 0)
            fresh = 1.0 if age <= self.freshness_ms else 0.5
        if memory.valid_to is not None and (self.as_of or fabric.now()) >= memory.valid_to:
            fresh = 0.2
        parts["freshness"] = fresh
        root = fabric.source_root(memory_id)
        parts["independence"] = 1.0 / (1 + seen_roots.get(root, 0))
        seen_roots[root] = seen_roots.get(root, 0) + 1
        preference = 1.0
        for c in self.preferred_evidence:
            if c.rule.holds(memory.context):
                preference *= 1 + c.weight * (0.25 if c.strength == "uncertain" else 1.0)
        for c in self.excluded_context:
            if c.strength != "hard" and c.rule.holds(memory.context):
                preference *= max(0.05, 1 - c.weight * (0.25 if c.strength == "uncertain" else 1.0))
        parts["preference"] = preference
        score = (parts["relevance"] * parts["authority"] * parts["kind"] * parts["freshness"]
                 * parts["independence"] * preference)
        return score, parts

    def rank(self, fabric: "MemoryFabric", hits: Sequence[tuple[str, float]]
             ) -> list[tuple[str, float]]:
        """Re-order retrieval hits by evidence. In `high` impact, drop untrusted evidence."""
        from . import authority

        seen: dict[str, int] = {}
        scored = []
        when = self.as_of if self.as_of is not None else fabric.now()
        for memory_id, relevance in hits:
            valid_to = fabric.state.memories[memory_id].valid_to
            if not self.include_history and valid_to is not None and when >= valid_to:
                continue
            if self.decision_impact == "high" and not authority.of(
                    fabric, memory_id).at_least(authority.UNVERIFIED):
                continue
            score, _ = self.evidence_score(fabric, memory_id, relevance, seen)
            if score > 0:
                scored.append((memory_id, score))
        return sorted(scored, key=lambda x: -x[1])

    def explain(self, fabric: "MemoryFabric", memory_ids: Sequence[str]) -> list[dict[str, Any]]:
        """Per memory: eligible or not, the reason, and the evidence parts. Ids only."""
        seen: dict[str, int] = {}
        out = []
        for memory_id in memory_ids:
            memory = fabric.state.memories[memory_id]
            ok, reason = self.eligibility(memory.context)
            _, parts = self.evidence_score(fabric, memory_id, 1.0, seen)
            out.append({"memory_id": memory_id, "eligible": ok, "reason": reason,
                        "safety": self.is_safety(memory.context), "evidence": parts})
        return out

    def omissions(self, contents: Sequence[str]) -> list[str]:
        """Required facts that no shown memory mentions (case-insensitive substring)."""
        low = [c.lower() for c in contents]
        return [f for f in self.required_facts if not any(f.lower() in c for c in low)]

    # --- serialisation ---------------------------------------------------

    def to_json(self) -> dict[str, Any]:
        return {"goal": self.goal, "required_facts": list(self.required_facts),
                "preferred_evidence": [c.to_json() for c in self.preferred_evidence],
                "excluded_context": [c.to_json() for c in self.excluded_context],
                "safety_constraints": [r.to_json() for r in self.safety_constraints],
                "scope": [[r.to_json() for r in g] for g in self.scope],
                "as_of": self.as_of, "freshness_ms": self.freshness_ms,
                "uncertainty_policy": self.uncertainty_policy,
                "decision_impact": self.decision_impact,
                "compiled_by": self.compiled_by, "reviewed_by": self.reviewed_by,
                "include_history": self.include_history}

    @classmethod
    def from_json(cls, d: Mapping[str, Any]) -> "MemoryObjectiveV2":
        return cls(goal=str(d.get("goal", "")), required_facts=tuple(d.get("required_facts", ())),
                   preferred_evidence=tuple(Constraint.from_json(c)
                                            for c in d.get("preferred_evidence", ())),
                   excluded_context=tuple(Constraint.from_json(c)
                                          for c in d.get("excluded_context", ())),
                   safety_constraints=tuple(Rule(**r) for r in d.get("safety_constraints", ())),
                   scope=tuple(tuple(Rule(**r) for r in g) for g in d.get("scope", ())),
                   as_of=d.get("as_of"), freshness_ms=d.get("freshness_ms"),
                   uncertainty_policy=str(d.get("uncertainty_policy", "surface")),
                   decision_impact=str(d.get("decision_impact", "low")),
                   compiled_by=d.get("compiled_by"), reviewed_by=d.get("reviewed_by"),
                   include_history=bool(d.get("include_history", False)))

    def digest(self) -> str:
        return hashlib.sha256(json.dumps(self.to_json(), sort_keys=True,
                                         default=str).encode()).hexdigest()[:32]

    def reviewed(self, reviewer: str) -> "MemoryObjectiveV2":
        """The same objective, marked reviewed. Its compiler cannot review it."""
        if reviewer == self.compiled_by:
            raise ValueError("an objective's compiler cannot review it")
        return replace(self, reviewed_by=reviewer)


def from_v1(v1: Any, compiled_by: str | None = None) -> MemoryObjectiveV2:
    """A V1 objective as V2: compiled rules become *uncertain* until reviewed."""
    strength = "uncertain" if compiled_by else "hard"
    return MemoryObjectiveV2(
        goal=v1.statement, scope=tuple(v1.include) if not compiled_by else (),
        preferred_evidence=tuple(Constraint(r, "uncertain") for g in v1.include for r in g)
        if compiled_by else (),
        excluded_context=tuple(Constraint(r, strength) for r in v1.exclude),
        compiled_by=compiled_by)


@dataclass
class ObjectiveLog:
    """Proposals and adoptions of objective changes, recorded in the store's log."""

    fabric: "MemoryFabric"
    history: list[dict[str, Any]] = field(default_factory=list)

    def propose(self, objective: MemoryObjectiveV2, proposer: str,
                evaluation: Mapping[str, float], reason: str) -> str:
        from . import events as ev

        payload = {"digest": objective.digest(), "status": "proposed", "proposer": proposer,
                   "evaluation": dict(evaluation), "reason": reason,
                   "objective": objective.to_json()}
        self.fabric._emit(ev.objective_changed(ts=self.fabric.now(), actor=proposer, **payload))
        return objective.digest()

    def adopt(self, digest: str, reviewer: str, baseline: Mapping[str, float],
              higher_is_better: Sequence[str] = ("accuracy",)) -> MemoryObjectiveV2:
        """Adopt a proposal: a different reviewer, and no registered metric got worse."""
        from . import events as ev

        proposal = next((e.payload for e in reversed(self.events())
                         if e.payload["digest"] == digest and e.payload["status"] == "proposed"),
                        None)
        if proposal is None:
            raise ValueError(f"no proposal {digest}")
        if reviewer == proposal["proposer"]:
            raise ValueError("a proposal cannot be adopted by its proposer")
        evaluation = proposal["evaluation"]
        worse = [m for m in higher_is_better
                 if float(evaluation.get(m, float("-inf"))) < float(baseline.get(m, 0.0))]
        if worse:
            self.fabric._emit(ev.objective_changed(
                ts=self.fabric.now(), actor=reviewer, digest=digest, status="rejected",
                proposer=proposal["proposer"], evaluation=evaluation,
                reason=f"worse on {worse}", objective=proposal["objective"]))
            raise ValueError(f"evaluation is worse than the baseline on {worse}")
        self.fabric._emit(ev.objective_changed(
            ts=self.fabric.now(), actor=reviewer, digest=digest, status="adopted",
            proposer=proposal["proposer"], evaluation=evaluation, reason="reviewed",
            objective=proposal["objective"]))
        return MemoryObjectiveV2.from_json(proposal["objective"])

    def events(self) -> list[Any]:
        from . import events as ev

        return list(self.fabric.log.read_types([ev.EventType.OBJECTIVE_CHANGED]))
