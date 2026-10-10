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
    DUPLICATE_SUPPRESSED = "MemoryDuplicateSuppressed"
    STORE_IDENTIFIED = "StoreIdentified"
    RETRACTION_REQUESTED = "RetractionRequested"
    RETRACTION_APPLIED = "RetractionApplied"
    RETRACTION_REJECTED = "RetractionRejected"
    PROPAGATION_STATE_CHANGED = "PropagationStateChanged"
    ACCESS_DENIED = "AccessDenied"
    SUPPORT_RECOMPUTED = "SupportRecomputed"
    ACCESS_DENIED = "AccessDenied"


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
    ts: int,
    memory_id: str,
    from_state: str,
    to_state: str,
    reason: str,
    actor: str,
    basis: str | None = None,
) -> Event:
    """`basis` is additive and optional, so logs written by 0.2.0 replay
    unchanged (VERSIONING.md). It is omitted from the payload when absent rather
    than written as a placeholder: an event that never carried a basis and one
    that carried "unstated" are different facts about what the caller knew.
    """
    payload = {
        "memory_id": memory_id,
        "from": from_state,
        "to": to_state,
        "reason": reason,
        "actor": actor,
    }
    if basis is not None:
        payload["basis"] = basis
    return Event(
        type=EventType.LIFECYCLE_CHANGED,
        ts=ts,
        agent_id=actor,
        payload=payload,
    )


def store_identified(ts: int, store_id: str, actor: str = "store") -> Event:
    """A store names itself, once, in its own log.

    The identity has to survive a restore from backup, and the log is the only
    thing guaranteed to. Deriving it from a config file means a mis-deployed
    config silently re-identifies a store and every retraction addressed to the
    old id goes nowhere.
    """
    return Event(
        type=EventType.STORE_IDENTIFIED,
        ts=ts,
        agent_id=actor,
        payload={"store_id": store_id},
    )


def retraction_requested(
    ts: int,
    retraction_id: str,
    origin_store_id: str,
    origin_memory_id: str,
    origin_memory_version: int,
    origin_sequence: int,
    reason_code: str,
    recipients: list[str],
    requested_by: str,
    evidence_digest: str | None = None,
) -> Event:
    """The origin's durable record that a retraction is owed to each recipient.

    Committed in the same transaction as the outbox rows, which is what makes
    invariant 3 ("a committed retraction cannot disappear because a process
    crashes before dispatch") expressible at all.
    """
    payload: dict[str, Any] = {
        "retraction_id": retraction_id,
        "origin_store_id": origin_store_id,
        "origin_memory_id": origin_memory_id,
        "origin_memory_version": origin_memory_version,
        "origin_sequence": origin_sequence,
        "reason_code": reason_code,
        "recipients": list(recipients),
        "requested_by": requested_by,
    }
    if evidence_digest is not None:
        payload["evidence_digest"] = evidence_digest
    return Event(
        type=EventType.RETRACTION_REQUESTED,
        ts=ts,
        agent_id=requested_by,
        payload=payload,
    )


def retraction_applied(
    ts: int,
    retraction_id: str,
    origin_store_id: str,
    origin_memory_id: str,
    origin_memory_version: int,
    local_memory_id: str,
    actor: str,
) -> Event:
    """A recipient's record that it applied a retraction locally."""
    return Event(
        type=EventType.RETRACTION_APPLIED,
        ts=ts,
        agent_id=actor,
        payload={
            "retraction_id": retraction_id,
            "origin_store_id": origin_store_id,
            "origin_memory_id": origin_memory_id,
            "origin_memory_version": origin_memory_version,
            "local_memory_id": local_memory_id,
        },
    )


def retraction_rejected(
    ts: int,
    retraction_id: str,
    origin_store_id: str,
    rejection_code: str,
    detail: str,
    actor: str,
) -> Event:
    """A recipient's record that it refused one. Refusals are auditable too:
    an unauthorised or superseded retraction that left no trace would be
    indistinguishable from one that never arrived."""
    return Event(
        type=EventType.RETRACTION_REJECTED,
        ts=ts,
        agent_id=actor,
        payload={
            "retraction_id": retraction_id,
            "origin_store_id": origin_store_id,
            "rejection_code": rejection_code,
            "detail": detail,
        },
    )


def propagation_state_changed(
    ts: int,
    retraction_id: str,
    recipient_store_id: str,
    from_state: str,
    to_state: str,
    detail: str = "",
    actor: str = "dispatcher",
) -> Event:
    """One (retraction, recipient) pair moving through the propagation state
    machine. Separate from `lifecycle_changed` because a memory can be
    retracted at source while one recipient is enforced and another offline;
    one state cannot represent both."""
    return Event(
        type=EventType.PROPAGATION_STATE_CHANGED,
        ts=ts,
        agent_id=actor,
        payload={
            "retraction_id": retraction_id,
            "recipient_store_id": recipient_store_id,
            "from": from_state,
            "to": to_state,
            "detail": detail,
        },
    )


def access_denied(
    ts: int,
    memory_id: str,
    version: int,
    agent_id: str,
    verdict: str,
    reason_code: str,
    risk: str,
    detail: str = "",
) -> Event:
    """A refusal, recorded without the content that was refused.

    Auditing a denial by logging what was denied would move memory content into
    exactly the secondary surfaces governance exists to keep it out of. The
    reviewer gets the memory id, the version, the reason code and the risk
    level, which is what the decision needs.
    """
    return Event(
        type=EventType.ACCESS_DENIED,
        ts=ts,
        agent_id=agent_id,
        payload={
            "memory_id": memory_id,
            "version": version,
            "verdict": verdict,
            "reason_code": reason_code,
            "risk": risk,
            "detail": detail[:256],
        },
    )


def access_denied(
    ts: int,
    memory_id: str,
    version: int,
    agent_id: str,
    verdict: str,
    reason_code: str,
    risk: str,
    detail: str = "",
) -> Event:
    """A refusal, recorded without the content that was refused.

    Auditing a denial by logging what was denied would move memory content into
    exactly the secondary surfaces governance exists to keep it out of. The
    reviewer gets the memory id, the version, the reason code and the risk
    level, which is what the decision needs.
    """
    return Event(
        type=EventType.ACCESS_DENIED,
        ts=ts,
        agent_id=agent_id,
        payload={
            "memory_id": memory_id,
            "version": version,
            "verdict": verdict,
            "reason_code": reason_code,
            "risk": risk,
            "detail": detail[:256],
        },
    )


def support_recomputed(
    ts: int,
    memory_id: str,
    trigger_memory_id: str,
    verdict: str,
    surviving: list[str],
    lost: list[str],
    independent_count: int,
    reason: str,
    actor: str,
) -> Event:
    """A conclusion's support was recomputed after a premise was invalidated.

    Emitted whether or not the conclusion survived, because "we checked and it
    still stands" is the fact an operator most needs and the one an
    unconditional contest loop could never record.
    """
    return Event(
        type=EventType.SUPPORT_RECOMPUTED,
        ts=ts,
        agent_id=actor,
        payload={
            "memory_id": memory_id,
            "trigger_memory_id": trigger_memory_id,
            "verdict": verdict,
            "surviving": list(surviving),
            "lost": list(lost),
            "independent_count": independent_count,
            "reason": reason[:256],
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


def duplicate_suppressed(
    ts: int,
    agent_id: str,
    episode_id: str | None,
    existing_memory_id: str,
    content_digest: str,
) -> Event:
    """An agent wrote the same thing twice within one episode.

    Recorded rather than silently dropped: the attempt is evidence about the
    agent, and without it the log would show a write that produced no memory.
    """
    return Event(
        type=EventType.DUPLICATE_SUPPRESSED,
        ts=ts,
        agent_id=agent_id,
        episode_id=episode_id,
        payload={
            "memory_id": existing_memory_id,
            "content_digest": content_digest,
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
