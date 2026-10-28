"""Explicit-ID historical reads with current authorization and bounded event replay.

Experimental archival results carry no exposure token or action certificate.
This module never changes the current projection or restores erased keys.
"""
from __future__ import annotations

__stability__ = "experimental"

from dataclasses import dataclass, field
import time
from typing import TYPE_CHECKING, Iterable

from . import events as ev
from .identity import DEFAULT_TENANT
from .model import EXPOSABLE_STATES, visible_to
from .navigation import _visible
from .projections import Projection

if TYPE_CHECKING:
    from .fabric import MemoryFabric


@dataclass(frozen=True)
class HistoricalRecord:
    memory_id: str
    version: int
    content: str
    recorded_at_ms: int
    recorded_seq: int
    valid_from: int | None
    valid_to: int | None
    current_version: int
    superseded: bool
    lineage: tuple[tuple[str, int], ...]
    lineage_redacted: bool = False
    archival_only: bool = True


@dataclass
class HistoryReceipt:
    known_at: int
    valid_at: int | None
    current_log_head: int
    events_replayed: int
    rows: list[HistoricalRecord] = field(default_factory=list)
    elapsed_ms: float = 0.0
    authority: str = "archival read only; not current action evidence"


def query(fabric: "MemoryFabric", agent_id: str, memory_ids: Iterable[str], *,
          known_at: int, valid_at: int | None = None, tenant_id: str = DEFAULT_TENANT,
          max_events: int = 10_000) -> HistoryReceipt:
    """Read requested IDs at an inclusive log sequence and optional valid-time point.

    Both historical and current permissions must allow access. Inaccessible IDs
    are omitted without counts or reasons that disclose former private records.
    A replay limit refuses the whole request rather than claiming a partial view.
    Current policy is fenced until exposures are logged and output materialized.
    """
    if type(known_at) is not int or known_at < 0:
        raise ValueError("known_at must be a non-negative log sequence")
    if type(max_events) is not int or not 1 <= max_events <= 100_000:
        raise ValueError("max_events must be between 1 and 100000")
    if valid_at is not None and type(valid_at) is not int:
        raise ValueError("valid_at must be an integer event-time value")
    if not agent_id or not tenant_id:
        raise ValueError("agent_id and tenant_id must be explicit non-empty identities")
    requested = []
    for index, mid in enumerate(memory_ids):
        if index >= 100:
            raise ValueError("historical reads accept at most 100 requested IDs")
        if not isinstance(mid, str):
            raise ValueError("memory IDs must be strings")
        if mid not in requested:
            requested.append(mid)
    start = time.perf_counter()
    with fabric._transaction():
        head = fabric.log.head_seq
        if known_at > head:
            raise ValueError("known_at exceeds the current log head")
        projection = Projection()
        recorded: dict[tuple[str, int], tuple[int, int]] = {}
        replayed = 0
        for event in fabric.log.read(limit=max_events + 1):
            if event.seq is not None and event.seq > known_at:
                break
            replayed += 1
            if replayed > max_events:
                raise ValueError("historical replay exceeds max_events; request a bounded snapshot")
            projection.apply(event)
            if event.type in {ev.EventType.MEMORY_CREATED, ev.EventType.MEMORY_VERSIONED}:
                memory = event.payload["memory"]
                recorded[(memory["id"], memory["version"])] = (event.ts, event.seq or 0)
        snapshot = projection.state
        allowed_now = set(_visible(fabric, agent_id, tenant_id)) - fabric.state.erased
        receipt = HistoryReceipt(known_at, valid_at, head, replayed)
        for mid in requested:
            historical = snapshot.memories.get(mid)
            if mid not in allowed_now or historical is None or mid in snapshot.erased:
                continue
            if (historical.tenant_id != tenant_id or historical.lifecycle_state not in EXPOSABLE_STATES
                    or not visible_to(historical, agent_id, snapshot)
                    or (valid_at is not None and not historical.applies_at(valid_at))):
                continue
            current = fabric.use(mid, agent_id=agent_id, tenant_id=tenant_id, audit=False)
            if not current.usable:
                continue
            text = fabric._unseal_content(historical.content, mid, historical.version)
            lineage = tuple((pid, ver) for pid, ver in historical.provenance.parents
                            if pid in allowed_now and pid in snapshot.memories
                            and visible_to(snapshot.memories[pid], agent_id, snapshot))
            now_version = fabric.state.memories[mid].version
            recorded_at, recorded_seq = recorded[(mid, historical.version)]
            receipt.rows.append(HistoricalRecord(mid, historical.version, text,
                recorded_at, recorded_seq, historical.valid_from, historical.valid_to, now_version,
                historical.version != now_version, lineage,
                lineage_redacted=len(lineage) != len(historical.provenance.parents)))
        fabric._emit(ev.retrieval_performed(fabric.now(), agent_id, None,
            "explicit historical ID read", [(r.memory_id, r.version, 1.0) for r in receipt.rows],
            {"archival_only": True, "known_at": known_at, "valid_at": valid_at}))
        for row in receipt.rows:
            fabric._emit(ev.exposure_decided(fabric.now(), agent_id, None, row.memory_id,
                row.version, True, 1.0, "history-explicit/1"))
        receipt.elapsed_ms = round((time.perf_counter() - start) * 1000, 3)
        return receipt
