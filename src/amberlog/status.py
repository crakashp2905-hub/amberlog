"""Four status labels, each saying what it does and does not establish.

A memory on screen invites one question -- *can I trust this?* -- and the
store can answer four narrower ones. Shown as one badge, they blur into a
claim nobody checked. So each is computed separately, from the log, and each
carries its own limits:

| label | established when | does **not** establish |
|---|---|---|
| **source recorded** | provenance names who wrote it and how | that the source is right, or trustworthy |
| **reviewed** | a person moved this version to `active` | that the reviewer checked it against anything |
| **policy-checked** | it passed the ingest screens of a version that screens every write path, and no screen has quarantined it | that it is safe: the screens catch known patterns only |
| **verified in destination** | every store a correction was owed to reported that it no longer serves the memory | independent confirmation -- each recipient reports on itself -- or anything about stores it never reached |

"Reviewed" is about *this* version, from the last activation in the log.
A memory created active by `auto_activate` or trusted-local mode was not
reviewed, and says so: auto-activation writes the memory as active, with no
lifecycle change for a person to have made.

"Policy-checked" is derived, not recorded. A clean screening is not written to
the log, but every write path has screened since schema 0.9.0 (the metadata
and `revise` bypasses were closed then), so a version written at 0.9.0 or
later that no screen quarantined passed them. An older version passed the
screens of its day, and the label says that instead.

"Verified in destination" rests on the recipient's own acknowledgement that
its projections stopped exposing the version (`enforced`). The protocol
defines a stronger state, `verified` -- the origin confirming it
independently -- but nothing in this codebase sets it, so the label cannot
claim it and says that the confirmation is self-reported. Closing that is
research task S1 in docs/WORKPLAN.md.
"""

from __future__ import annotations

__stability__ = "beta"

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Iterable, Mapping

from .events import EventType
from .model import LifecycleState, WithdrawalBasis
from .protocol import PropagationState

if TYPE_CHECKING:  # pragma: no cover
    from .fabric import Amberlog

SCREENS_EVERY_PATH_SINCE = (0, 9, 0)
SCREEN_BASES = frozenset({WithdrawalBasis.SENSITIVE_DATA.value})
# Actors that move memories without a person deciding. A store's own id acts
# for federation and truth maintenance; the firewall for its screens.
_AUTOMATIC = frozenset({"copy-recognition", "retention", "trusted-local", "system"})


@dataclass(frozen=True)
class StatusLabel:
    key: str
    label: str
    established: bool | None
    """True, False, or None when it does not apply (a memory never shared has
    nothing to verify in a destination)."""
    detail: str
    means: str
    does_not_mean: str

    def to_json(self) -> dict[str, Any]:
        return dict(self.__dict__)


_MEANS = {
    "source_recorded": ("who wrote it and how is on record",
                        "that the source is right, or trustworthy"),
    "reviewed": ("a person moved this version to active",
                 "that the reviewer checked it against anything"),
    "policy_checked": ("it passed the ingest screens and none has quarantined it",
                       "that it is safe: the screens catch known patterns only"),
    "verified_in_destination": ("every store owed a correction reported that it no longer "
                                "serves the memory",
                                "independent confirmation (each recipient reports on itself), "
                                "or anything about stores the memory never reached"),
}
_LABEL = {"source_recorded": "source recorded", "reviewed": "reviewed",
          "policy_checked": "policy-checked",
          "verified_in_destination": "verified in destination"}


def _make(key: str, established: bool | None, detail: str) -> StatusLabel:
    means, not_mean = _MEANS[key]
    return StatusLabel(key, _LABEL[key], established, detail, means, not_mean)


def _version_tuple(text: str) -> tuple[int, ...]:
    try:
        return tuple(int(p) for p in text.split("."))
    except ValueError:
        return (0,)


class _Index:
    """One pass over the events these labels read, for any number of memories."""

    def __init__(self, fabric: "Amberlog") -> None:
        self.activation: dict[str, Any] = {}
        self.revised_since_review: set[str] = set()
        self.version_schema: dict[tuple[str, int], str] = {}
        self.retractions: dict[str, list[Mapping[str, Any]]] = {}
        types = [EventType.LIFECYCLE_CHANGED, EventType.MEMORY_CREATED,
                 EventType.MEMORY_VERSIONED, EventType.RETRACTION_REQUESTED]
        for event in fabric.log.read_types(types):
            payload = event.payload
            if event.type == EventType.LIFECYCLE_CHANGED:
                if payload.get("to") == LifecycleState.ACTIVE.value:
                    self.activation[payload["memory_id"]] = event
                    self.revised_since_review.discard(payload["memory_id"])
            elif event.type in (EventType.MEMORY_CREATED,
                                EventType.MEMORY_VERSIONED):
                memory = payload.get("memory") or {}
                key = (memory.get("id", ""), int(memory.get("version", 1)))
                self.version_schema[key] = event.schema_version
                if event.type == EventType.MEMORY_VERSIONED:
                    # A new version needs its own review: any activation
                    # before it, in log order, was of different content.
                    if self.activation.pop(key[0], None) is not None:
                        self.revised_since_review.add(key[0])
            else:
                self.retractions.setdefault(payload.get("origin_memory_id", ""), []).append(payload)


def labels(fabric: "Amberlog", memory_id: str, _index: _Index | None = None) -> list[StatusLabel]:
    """The four labels for one memory, in display order."""
    index = _index or _Index(fabric)
    memory = fabric.state.memories[memory_id]
    out = []

    prov = memory.provenance
    out.append(_make("source_recorded", bool(prov.created_by),
                     f"written by {prov.created_by} ({prov.method.value}); "
                     f"{len(prov.source_episodes)} source episode(s), "
                     f"{len(prov.parents)} parent memory(ies)"
                     if prov.created_by else "no author recorded"))

    automatic = {fabric.firewall.id, fabric.store_id, *_AUTOMATIC}
    if memory.context.get("activation") == "trusted-local":
        out.append(_make("reviewed", False, "active without review (trusted-local mode)"))
    elif memory.lifecycle_state is not LifecycleState.ACTIVE:
        out.append(_make("reviewed", False,
                         f"not active: {memory.lifecycle_state.value}"))
    else:
        event = index.activation.get(memory_id)
        actor = (event.payload.get("actor") or "") if event is not None else ""
        if event is None and memory_id in index.revised_since_review:
            out.append(_make("reviewed", False,
                             f"version {memory.version} was written after the last review"))
        elif event is None:
            out.append(_make("reviewed", False,
                             "created active without review (auto-activation)"))
        elif actor in automatic:
            out.append(_make("reviewed", False, f"activated automatically by {actor}"))
        else:
            out.append(_make("reviewed", True, f"activated by {actor}"))

    basis = fabric.state.withdrawal_basis.get(memory_id)
    schema = index.version_schema.get((memory_id, memory.version), "")
    if memory.lifecycle_state is LifecycleState.QUARANTINED and basis in SCREEN_BASES:
        out.append(_make("policy_checked", False, "quarantined by an ingest screen"))
    elif not schema:
        out.append(_make("policy_checked", None, "no creation event found for this version"))
    elif _version_tuple(schema) >= SCREENS_EVERY_PATH_SINCE:
        out.append(_make("policy_checked", True,
                         f"written at schema {schema}, which screens every write path"))
    else:
        out.append(_make("policy_checked", False,
                         f"written at schema {schema}, before every write path was "
                         f"screened; it passed the screens of that version"))

    campaigns = index.retractions.get(memory_id, [])
    if not campaigns:
        out.append(_make("verified_in_destination", None, "no correction was owed to another store"))
    else:
        owed: set[str] = set()
        confirmed: set[str] = set()
        done = (PropagationState.ENFORCED, PropagationState.VERIFIED)
        for payload in campaigns:
            recipients = set(payload.get("recipients") or ())
            owed |= recipients
            acks = fabric.outbox.acknowledgements(payload.get("retraction_id", ""))
            confirmed |= {r for r, ack in acks.items() if ack.state in done and r in recipients}
        if not owed:
            out.append(_make("verified_in_destination", None,
                             "retracted, with no other store to tell"))
        else:
            out.append(_make("verified_in_destination", confirmed >= owed,
                             f"{len(confirmed & owed)} of {len(owed)} store(s) report it "
                             f"enforced (self-reported)"))
    return out


def labels_for(fabric: "Amberlog", memory_ids: Iterable[str]) -> dict[str, list[StatusLabel]]:
    """Labels for many memories from one pass over the log."""
    index = _Index(fabric)
    return {m: labels(fabric, m, index) for m in memory_ids if m in fabric.state.memories}
