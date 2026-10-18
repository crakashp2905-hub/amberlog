"""Projections: in-memory state derived from the event log.

Rebuilding from seq 0 must always produce identical state (the P1 gate in
ROADMAP.md). So `apply` is pure with respect to the event stream: it reads
nothing but events, and unknown event types are ignored rather than fatal.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field, replace
from typing import Any, Iterable, Mapping

from .events import Event, EventType
from .governance.erasure import ERASED_MARKER
from .model import (
    LifecycleState,
    WithdrawalBasis,
    Memory,
    MemoryStats,
    Scope,
    ValueEstimate,
)


@dataclass
class Episode:
    id: str
    agent_id: str
    task_id: str
    context: Mapping[str, Any]
    seed: int | None = None
    started_at: int = 0
    outcome: float | None = None
    verifier_id: str | None = None
    outcome_at: int | None = None

    @property
    def has_outcome(self) -> bool:
        return self.outcome is not None


@dataclass
class ExposureRecord:
    """One logged exposure decision, the atom of causal-credit estimation."""

    episode_id: str | None
    memory_id: str
    version: int
    exposed: bool
    propensity: float
    policy_id: str
    step: int
    ts: int


@dataclass
class DuplicateKey:
    """Identity of a write within one episode, for suppressing tool-call loops."""

    agent_id: str
    episode_id: str
    digest: str


@dataclass
class HypothesisSet:
    """A group of mutually contradictory memories, kept rather than collapsed."""

    id: str
    memory_ids: set[str] = field(default_factory=set)
    detector_id: str = ""
    confidence: float = 0.0
    resolved: bool = False
    opened_at: int = 0


@dataclass
class ProjectionState:
    memories: dict[str, Memory] = field(default_factory=dict)
    history: dict[str, list[Memory]] = field(default_factory=dict)
    stats: dict[str, MemoryStats] = field(default_factory=dict)
    episodes: dict[str, Episode] = field(default_factory=dict)
    exposures: list[ExposureRecord] = field(default_factory=list)
    hypothesis_sets: dict[str, HypothesisSet] = field(default_factory=dict)
    children: dict[str, set[str]] = field(default_factory=dict)
    parents: dict[str, set[str]] = field(default_factory=dict)
    # (agent, episode, content digest) -> memory already written for it.
    written: dict[tuple[str, str, str], str] = field(default_factory=dict)
    # memory id -> the basis given the last time it was withdrawn. Kept as a
    # projection rather than a field on Memory because it is a property of the
    # decision, not of the memory, and a release leaves it readable.
    withdrawal_basis: dict[str, str] = field(default_factory=dict)
    copy_of: dict[str, str] = field(default_factory=dict)
    """Memory id -> the memory it re-ingests.

    Deliberately not a parent edge. `_group_by_root` spares a memory that is
    derivation-related to something already kept, because a premise and its
    conclusion are not copies -- so recording a copy as a child would exempt it
    from the grouping that exists to collapse it.
    """
    copies: dict[str, set[str]] = field(default_factory=dict)
    """The reverse index, so retraction can follow copy edges outward."""
    relations: dict[tuple[str, str], set[str]] = field(default_factory=dict)
    """(subject, kind) -> the objects it stands in that relation to."""
    related_to: dict[tuple[str, str], set[str]] = field(default_factory=dict)
    """(object, kind) -> the subjects standing in that relation to it.

    Both directions are indexed because retrieval needs both: a selected
    memory drags in whatever *qualifies* it, which is a reverse lookup, and a
    rule's applicability is decided by what *excepts* it, which is the same
    lookup from the other side.
    """
    # This store's own opaque identity, recorded in its log so it survives a
    # restore from backup. None until a StoreIdentified event has been seen.
    store_id: str | None = None
    # (child, parent) -> the exact parent version the child was derived from.
    # Provenance has always recorded it; the projection used to throw it away,
    # which left retraction targeting ids and enforcement per-memory rather
    # than per-version. Four partial invariants shared that root cause.
    parent_versions: dict[tuple[str, str], int] = field(default_factory=dict)
    # Per-origin monotonic counter for integrity events this store emits.
    origin_sequence: int = 0
    # Memories whose content key has been destroyed. Replayed from the log,
    # so erasure survives a rebuild rather than depending on the key table.
    erased: set[str] = field(default_factory=set)
    # local memory id -> the stores this one sent it to, and the id each gave
    # it. The forwarding table a transitive retraction walks.
    shared_to: dict[str, dict[str, str]] = field(default_factory=dict)
    # (tenant, collection name) -> members and per-agent grants (0.10.0).
    collections: dict[tuple[str, str], "CollectionState"] = field(default_factory=dict)
    suppressed_duplicates: int = 0
    applied_seq: int = 0

    def stats_for(self, memory_id: str) -> MemoryStats:
        if memory_id not in self.stats:
            self.stats[memory_id] = MemoryStats(memory_id=memory_id)
        return self.stats[memory_id]


class Projection:
    """Folds the event log into queryable state.

    `unsealer` is the one seam encryption needs. This is the single place a
    `Memory` object is built from an event, so unsealing here means every
    downstream reader of `.content` — thirty call sites across eleven modules —
    sees plaintext and needs no change. The log holds ciphertext; the projection
    holds what the caller asked for.

    Defaults to identity so the projection stays independently testable and so
    a log written before encryption existed replays unchanged.
    """

    def __init__(self, unsealer=None) -> None:
        self.state = ProjectionState()
        self._unseal = unsealer or (
            lambda content, memory_id, version: content
        )

    def apply(self, event: Event) -> None:
        if event.type in (EventType.MEMORY_CREATED, EventType.MEMORY_VERSIONED):
            payload = dict(event.payload)
            memory = payload.get("memory") or {}
            content = memory.get("content")
            if isinstance(content, str):
                memory = dict(memory)
                # The version is passed because a ciphertext is bound to it:
                # authenticated encryption stops an old version's content being
                # pasted over the current one, which would roll a memory back
                # after a correction without touching the log.
                memory["content"] = self._unseal(
                    content, memory.get("id", ""), int(memory.get("version", 1))
                )
                payload["memory"] = memory
                event = replace(event, payload=payload)
        handler = _HANDLERS.get(event.type)
        if handler is not None:
            handler(self.state, event)
        # An unknown type is a newer schema writing events we do not model yet.
        # Ignoring it keeps old readers working (SPEC.md section 8).
        if event.seq is not None:
            self.state.applied_seq = max(self.state.applied_seq, event.seq)

    def apply_all(self, events: Iterable[Event]) -> None:
        for event in events:
            self.apply(event)

    @classmethod
    def rebuild(cls, log, since_seq: int = 0, unsealer=None) -> "Projection":
        """Fold a log into fresh state.

        `unsealer` has to be threaded through: a rebuild that dropped it would
        replace a configured projection with a default one and every memory
        would read back as ciphertext. `MemoryFabric._replay` calls this, so
        forgetting it broke reads on the first encrypted write.
        """
        projection = cls(unsealer=unsealer)
        projection.apply_all(log.read(since_seq=since_seq))
        return projection


# --- handlers ---------------------------------------------------------------


def _on_episode_started(state: ProjectionState, event: Event) -> None:
    episode_id = event.episode_id or event.payload.get("episode_id")
    if not episode_id:
        return
    state.episodes[episode_id] = Episode(
        id=episode_id,
        agent_id=event.agent_id or "",
        task_id=event.payload.get("task_id", ""),
        context=event.payload.get("context", {}),
        seed=event.payload.get("seed"),
        started_at=event.ts,
    )


def _register_memory(state: ProjectionState, memory: Memory) -> None:
    previous = state.memories.get(memory.id)
    if previous is not None:
        state.history.setdefault(memory.id, []).append(previous)
    state.memories[memory.id] = memory
    state.stats_for(memory.id)
    # Derivation edges. Recorded per memory id, not per version: lineage
    # questions ("what descends from this?") are asked about memories.
    for parent_id, version in memory.provenance.parents:
        state.children.setdefault(parent_id, set()).add(memory.id)
        state.parents.setdefault(memory.id, set()).add(parent_id)
        state.parent_versions[(memory.id, parent_id)] = version
    if memory.hypothesis_set:
        hset = state.hypothesis_sets.setdefault(
            memory.hypothesis_set, HypothesisSet(id=memory.hypothesis_set)
        )
        hset.memory_ids.add(memory.id)


def _on_memory_created(state: ProjectionState, event: Event) -> None:
    memory = Memory.from_json(event.payload["memory"])
    _register_memory(state, memory)
    if event.episode_id:
        key = (memory.provenance.created_by, event.episode_id, _digest(memory.content))
        state.written.setdefault(key, memory.id)


def _on_memory_versioned(state: ProjectionState, event: Event) -> None:
    _register_memory(state, Memory.from_json(event.payload["memory"]))


def _on_duplicate_suppressed(state: ProjectionState, event: Event) -> None:
    state.suppressed_duplicates += 1


def _digest(content: str) -> str:
    """Normalised digest: whitespace and case differences are not new content."""
    return hashlib.sha256(" ".join(content.lower().split()).encode()).hexdigest()


def _on_exposure_decided(state: ProjectionState, event: Event) -> None:
    payload = event.payload
    record = ExposureRecord(
        episode_id=event.episode_id,
        memory_id=payload["memory_id"],
        version=int(payload["version"]),
        exposed=bool(payload["exposed"]),
        propensity=float(payload["propensity"]),
        policy_id=payload.get("policy_id", ""),
        step=int(payload.get("step", 0)),
        ts=event.ts,
    )
    state.exposures.append(record)
    stats = state.stats_for(record.memory_id)
    if record.exposed:
        stats.exposures += 1
        stats.last_exposed_at = event.ts
    else:
        stats.withholdings += 1


def _on_memory_cited(state: ProjectionState, event: Event) -> None:
    state.stats_for(event.payload["memory_id"]).citations += 1


def _on_outcome_recorded(state: ProjectionState, event: Event) -> None:
    episode = state.episodes.get(event.episode_id or "")
    if episode is None:
        return
    episode.outcome = float(event.payload["outcome"])
    episode.verifier_id = event.payload.get("verifier_id")
    episode.outcome_at = event.ts


def _on_value_estimated(state: ProjectionState, event: Event) -> None:
    payload = event.payload
    raw = dict(payload["estimate"])
    raw.setdefault("estimator", payload.get("estimator_id", ""))
    raw["updated_at"] = event.ts
    estimate = ValueEstimate.from_json(raw)
    stats = state.stats_for(payload["memory_id"])
    key = payload.get("context_key", "*")
    if key == "*":
        stats.value_estimate = estimate
    else:
        stats.value_by_context[key] = estimate


def _on_lifecycle_changed(state: ProjectionState, event: Event) -> None:
    memory = state.memories.get(event.payload["memory_id"])
    if memory is None:
        return
    to_state = LifecycleState(event.payload["to"])
    state.memories[memory.id] = memory.evolve(lifecycle_state=to_state)
    if to_state in (LifecycleState.QUARANTINED, LifecycleState.DEPRECATED):
        state.withdrawal_basis[memory.id] = event.payload.get(
            "basis", WithdrawalBasis.UNSTATED.value
        )


def _on_store_identified(state: ProjectionState, event: Event) -> None:
    state.store_id = event.payload["store_id"]


def _on_retraction_requested(state: ProjectionState, event: Event) -> None:
    state.origin_sequence = max(
        state.origin_sequence, int(event.payload.get("origin_sequence", 0))
    )


def _on_memory_shared(state: ProjectionState, event: Event) -> None:
    state.shared_to.setdefault(event.payload["memory_id"], {})[
        event.payload["recipient_store_id"]
    ] = event.payload["imported_memory_id"]


def _on_content_erased(state: ProjectionState, event: Event) -> None:
    memory_id = event.payload["memory_id"]
    state.erased.add(memory_id)
    memory = state.memories.get(memory_id)
    if memory is not None:
        # Replace the stored text in the projection too. The event log keeps the
        # ciphertext, which without its key is not content.
        state.memories[memory_id] = memory.evolve(content=ERASED_MARKER)
    # And every earlier version. One key seals them all, so a replay after the
    # erasure reads each of them back as the marker -- but a process that was
    # already running kept their plaintext in `history`, and `history()` and
    # the dashboard's version list served it after the erasure was recorded.
    # Found by tests/test_catch_up.py comparing a live projection with a
    # replayed one.
    if memory_id in state.history:
        state.history[memory_id] = [
            old.evolve(content=ERASED_MARKER) for old in state.history[memory_id]]


def _on_scope_changed(state: ProjectionState, event: Event) -> None:
    memory = state.memories.get(event.payload["memory_id"])
    if memory is None:
        return
    state.memories[memory.id] = memory.evolve(scope=Scope(event.payload["to"]))


def _on_conflict_detected(state: ProjectionState, event: Event) -> None:
    payload = event.payload
    set_id = payload["hypothesis_set"]
    hset = state.hypothesis_sets.setdefault(
        set_id, HypothesisSet(id=set_id, opened_at=event.ts)
    )
    hset.memory_ids.update(payload["memory_ids"])
    hset.detector_id = payload.get("detector_id", hset.detector_id)
    hset.confidence = float(payload.get("confidence", hset.confidence))
    for memory_id in payload["memory_ids"]:
        memory = state.memories.get(memory_id)
        if memory is not None and memory.hypothesis_set != set_id:
            state.memories[memory_id] = memory.evolve(hypothesis_set=set_id)


def _on_experiment_run(state: ProjectionState, event: Event) -> None:
    hset = state.hypothesis_sets.get(event.payload["hypothesis_set"])
    if hset is not None and event.payload.get("results", {}).get("resolved"):
        hset.resolved = True


def _on_memories_related(state: ProjectionState, event: Event) -> None:
    subject = event.payload["subject_memory_id"]
    kind = event.payload["kind"]
    obj = event.payload["object_memory_id"]
    state.relations.setdefault((subject, kind), set()).add(obj)
    state.related_to.setdefault((obj, kind), set()).add(subject)


def _on_copy_recognised(state: ProjectionState, event: Event) -> None:
    memory_id = event.payload["memory_id"]
    original = event.payload["original_memory_id"]
    state.copy_of[memory_id] = original
    state.copies.setdefault(original, set()).add(memory_id)


@dataclass
class CollectionState:
    members: set[str] = field(default_factory=set)
    grants: dict[str, set[str]] = field(default_factory=dict)


def _on_collection_changed(state: ProjectionState, event: Event) -> None:
    p = event.payload
    collection = state.collections.setdefault((p["tenant_id"], p["collection"]),
                                              CollectionState())
    action = p.get("action")
    if action == "add" and p.get("memory_id"):
        collection.members.add(p["memory_id"])
    elif action == "remove" and p.get("memory_id"):
        collection.members.discard(p["memory_id"])
    elif action == "grant" and p.get("agent_id"):
        collection.grants.setdefault(p["agent_id"], set()).update(p.get("permissions") or ())
    elif action == "revoke" and p.get("agent_id"):
        held = collection.grants.get(p["agent_id"], set())
        held -= set(p.get("permissions") or held)
        if not held:
            collection.grants.pop(p["agent_id"], None)


_HANDLERS = {
    EventType.EPISODE_STARTED: _on_episode_started,
    EventType.MEMORY_CREATED: _on_memory_created,
    EventType.MEMORY_VERSIONED: _on_memory_versioned,
    EventType.EXPOSURE_DECIDED: _on_exposure_decided,
    EventType.MEMORY_CITED: _on_memory_cited,
    EventType.OUTCOME_RECORDED: _on_outcome_recorded,
    EventType.VALUE_ESTIMATED: _on_value_estimated,
    EventType.LIFECYCLE_CHANGED: _on_lifecycle_changed,
    EventType.SCOPE_CHANGED: _on_scope_changed,
    EventType.CONFLICT_DETECTED: _on_conflict_detected,
    EventType.EXPERIMENT_RUN: _on_experiment_run,
    EventType.DUPLICATE_SUPPRESSED: _on_duplicate_suppressed,
    EventType.COPY_RECOGNISED: _on_copy_recognised,
    EventType.MEMORIES_RELATED: _on_memories_related,
    EventType.STORE_IDENTIFIED: _on_store_identified,
    EventType.RETRACTION_REQUESTED: _on_retraction_requested,
    EventType.CONTENT_ERASED: _on_content_erased,
    EventType.MEMORY_SHARED: _on_memory_shared,
    EventType.COLLECTION_CHANGED: _on_collection_changed,
}
