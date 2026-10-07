"""Event types, per SPEC.md section 4.

The event log is the source of truth (AGENTS.md principle 3). Every other piece
of state in the system is a projection of these events and can be rebuilt from
them. Events are therefore append-only and never mutated.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from .ids import new_ulid
from .model import SCHEMA_VERSION, Memory


class EventType:
    EPISODE_STARTED = "EpisodeStarted"
    MEMORY_CREATED = "MemoryCreated"
    MEMORY_VERSIONED = "MemoryVersioned"
    RETRIEVAL_PERFORMED = "RetrievalPerformed"
    EXPOSURE_DECIDED = "ExposureDecided"
    MEMORY_CITED = "MemoryCited"
    OUTCOME_RECORDED = "OutcomeRecorded"
    VALUE_ESTIMATED = "ValueEstimated"
    LIFECYCLE_CHANGED = "LifecycleChanged"
    SCOPE_CHANGED = "ScopeChanged"
    CONFLICT_DETECTED = "ConflictDetected"
    EXPERIMENT_RUN = "ExperimentRun"


@dataclass(frozen=True)
class Event:
    """An immutable log record.

    `seq` is assigned by the log on append and is the authoritative ordering.
    """

    type: str
    ts: int
    payload: Mapping[str, Any] = field(default_factory=dict)
    agent_id: str | None = None
    episode_id: str | None = None
    event_id: str = field(default_factory=new_ulid)
    schema_version: str = SCHEMA_VERSION
    seq: int | None = None

    def with_seq(self, seq: int) -> "Event":
        return Event(
            type=self.type,
            ts=self.ts,
            payload=self.payload,
            agent_id=self.agent_id,
            episode_id=self.episode_id,
            event_id=self.event_id,
            schema_version=self.schema_version,
            seq=seq,
        )


# --- Constructors -----------------------------------------------------------
#
# Free functions rather than subclasses: the log stores one uniform row shape,
# and projections dispatch on `type`. This keeps the schema additive and makes
# forward compatibility (an unknown event type) a non-event.


def episode_started(ts: int, agent_id: str, episode_id: str, task_id: str, context: Mapping[str, Any], seed: int | None) -> Event:
    return Event(
        type=EventType.EPISODE_STARTED,
        ts=ts,
        agent_id=agent_id,
        episode_id=episode_id,
        payload={"task_id": task_id, "context": dict(context), "seed": seed},
    )


def memory_created(ts: int, memory: Memory, episode_id: str | None = None) -> Event:
    return Event(
        type=EventType.MEMORY_CREATED,
        ts=ts,
        agent_id=memory.provenance.created_by,
        episode_id=episode_id,
        payload={"memory": memory.to_json()},
    )


def memory_versioned(ts: int, memory: Memory, reason: str, episode_id: str | None = None) -> Event:
    return Event(
        type=EventType.MEMORY_VERSIONED,
        ts=ts,
        agent_id=memory.provenance.created_by,
        episode_id=episode_id,
        payload={"memory": memory.to_json(), "reason": reason},
    )


def retrieval_performed(
    ts: int,
    agent_id: str,
    episode_id: str | None,
    query: str,
    candidates: list[tuple[str, int, float]],
    context: Mapping[str, Any] | None,
) -> Event:
    """Records what was *available*, not what was shown."""
    return Event(
        type=EventType.RETRIEVAL_PERFORMED,
        ts=ts,
        agent_id=agent_id,
        episode_id=episode_id,
        payload={
            "query": query,
            "context": dict(context or {}),
            "candidates": [
                {"memory_id": mid, "version": ver, "score": score} for mid, ver, score in candidates
            ],
        },
    )


def exposure_decided(
    ts: int,
    agent_id: str,
    episode_id: str | None,
    memory_id: str,
    version: int,
    exposed: bool,
    propensity: float,
    policy_id: str,
    step: int = 0,
) -> Event:
    """The event that makes unbiased value estimation possible later.

    `propensity` is the probability with which *this* decision was taken, so a
    withheld memory records P(withhold). Retrofitting this field is impossible,
    which is why it exists from day one (ROADMAP.md, carried-over items).
    """
    return Event(
        type=EventType.EXPOSURE_DECIDED,
        ts=ts,
        agent_id=agent_id,
        episode_id=episode_id,
        payload={
            "memory_id": memory_id,
            "version": version,
            "exposed": exposed,
            "propensity": propensity,
            "policy_id": policy_id,
            "step": step,
        },
    )


def memory_cited(ts: int, agent_id: str, episode_id: str | None, memory_id: str, step: int = 0) -> Event:
    """The agent claims it used the memory. A weak, self-reported signal: never
    an input to value estimation, only a diagnostic."""
    return Event(
        type=EventType.MEMORY_CITED,
        ts=ts,
        agent_id=agent_id,
        episode_id=episode_id,
        payload={"memory_id": memory_id, "step": step},
    )


def outcome_recorded(ts: int, episode_id: str, outcome: float, verifier_id: str) -> Event:
    """Outcomes come from the environment or an evaluator. Self-reported
    outcomes are rejected upstream (SECURITY.md T2)."""
    return Event(
        type=EventType.OUTCOME_RECORDED,
        ts=ts,
        episode_id=episode_id,
        payload={"outcome": outcome, "verifier_id": verifier_id},
    )


def value_estimated(ts: int, memory_id: str, context_key: str, estimate: Mapping[str, Any], estimator_id: str) -> Event:
    return Event(
        type=EventType.VALUE_ESTIMATED,
        ts=ts,
        payload={
            "memory_id": memory_id,
            "context_key": context_key,
            "estimate": dict(estimate),
            "estimator_id": estimator_id,
        },
    )


def lifecycle_changed(
    ts: int, memory_id: str, from_state: str, to_state: str, reason: str, actor: str
) -> Event:
    return Event(
        type=EventType.LIFECYCLE_CHANGED,
        ts=ts,
        agent_id=actor,
        payload={
            "memory_id": memory_id,
            "from": from_state,
            "to": to_state,
            "reason": reason,
            "actor": actor,
        },
    )


def scope_changed(
    ts: int,
    memory_id: str,
    from_scope: str,
    to_scope: str,
    firewall_decision: str,
    reasons: list[str],
    actor: str,
) -> Event:
    return Event(
        type=EventType.SCOPE_CHANGED,
        ts=ts,
        agent_id=actor,
        payload={
            "memory_id": memory_id,
            "from": from_scope,
            "to": to_scope,
            "firewall_decision": firewall_decision,
            "reasons": reasons,
            "actor": actor,
        },
    )


def conflict_detected(
    ts: int,
    memory_ids: list[str],
    detector_id: str,
    confidence: float,
    hypothesis_set: str,
    actor: str | None = None,
) -> Event:
    return Event(
        type=EventType.CONFLICT_DETECTED,
        ts=ts,
        agent_id=actor,
        payload={
            "memory_ids": list(memory_ids),
            "detector_id": detector_id,
            "confidence": confidence,
            "hypothesis_set": hypothesis_set,
        },
    )


def experiment_run(ts: int, hypothesis_set: str, design: Mapping[str, Any], results: Mapping[str, Any]) -> Event:
    return Event(
        type=EventType.EXPERIMENT_RUN,
        ts=ts,
        payload={
            "hypothesis_set": hypothesis_set,
            "design": dict(design),
            "results": dict(results),
        },
    )
