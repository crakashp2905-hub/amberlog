"""Claim validation: is a new memory plausible, given everything the store already knows?

A text screen cannot see a plain false claim: "the purge time for P1 is 10 s"
reads exactly like a true one. But a store that has been running knows a
great deal about what is plausible, and most poisons are not plausible
against that knowledge. `assess` checks a memory's claim (`conflicts.claim`:
its identifiers, content words and values) against the store:

| signal | meaning | weight |
|---|---|---|
| `reasserts_corrected` | it states a value that was **withdrawn** for this same claim | suspicious |
| `contradicts_established` | an active memory by another author, with a track record, gives another value for this claim and has been in the store longer | suspicious |
| `outlier` | its value is far outside what the store holds for this kind of parameter on other equipment: robust z > 3.5 **and** beyond twice the largest or half the smallest of at least 5 comparable claims | suspicious |
| `new_source` | its author has no validated memory older than this one | provisional |
| `untrusted_origin` | its origin-bound authority is untrusted (tool output, import, web) | provisional |
| `corroborated` | another independent source (a different source root) states the same claim and value | supporting |

`level` is the summary: `suspicious` if any suspicious signal holds;
otherwise `corroborated` if supported; otherwise `provisional` if any
provisional signal holds; otherwise `unremarkable`.

**What it still cannot see, stated:** a plausible, in-range claim about
something the store has never heard of, from a source with a clean record.
That is the fundamental limit. `new_source` narrows it (a first claim from
an unknown author is provisional), and the action gate can require
corroboration for consequential use (`ToolRule.refuse_suspicious`,
`ToolRule.min_independent_sources`). Measured in
`research/results/v1-claim-validation.md`.
"""

from __future__ import annotations

__stability__ = "beta"

import statistics
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from .conflicts import author, claim

if TYPE_CHECKING:  # pragma: no cover
    from .fabric import MemoryFabric

SUSPICIOUS = ("reasserts_corrected", "contradicts_established", "outlier")
PROVISIONAL = ("new_source", "untrusted_origin")
OUTLIER_Z = 3.5
MIN_COMPARABLE = 5


@dataclass(frozen=True)
class Assessment:
    memory_id: str
    level: str
    signals: dict[str, str] = field(default_factory=dict)
    """signal -> the evidence for it (memory ids, numbers), for a reviewer."""

    @property
    def suspicious(self) -> bool:
        return self.level == "suspicious"


def _number(values: frozenset[str]) -> float | None:
    nums = []
    for v in values:
        try:
            nums.append(float(v))
        except ValueError:
            continue
    return nums[0] if len(nums) == 1 else None


def _same_claim(a: tuple, b: tuple) -> bool:
    """Same identifiers and at least two shared content words (or all, if fewer)."""
    ids_a, words_a, _ = a
    ids_b, words_b, _ = b
    if not ids_a or ids_a != ids_b:
        return False
    need = min(2, len(words_a), len(words_b))
    return len(words_a & words_b) >= max(1, need)


def _same_parameter(a: tuple, b: tuple) -> bool:
    """Another identifier, but the same kind of parameter: two shared content words."""
    ids_a, words_a, _ = a
    ids_b, words_b, _ = b
    return bool(ids_a) and bool(ids_b) and ids_a != ids_b and len(words_a & words_b) >= 2


def assess(fabric: "MemoryFabric", memory_id: str) -> Assessment:
    """Check one memory's claim against the store. Reads only; never changes state."""
    return _assess(fabric, fabric.state.memories[memory_id], with_authority=True)


def assess_write(fabric: "MemoryFabric", agent_id: str, content: str,
                 context: Any = None, tenant_id: str | None = None) -> Assessment:
    """Assess a write before it is stored: what the ingest hold uses (`hold_suspicious`)."""
    from types import SimpleNamespace

    from .model import DEFAULT_TENANT

    pending = SimpleNamespace(
        id="", content=content, context=dict(context or {}),
        tenant_id=tenant_id or DEFAULT_TENANT, created_at=fabric.now() + 1,
        provenance=SimpleNamespace(created_by=agent_id))
    return _assess(fabric, pending, with_authority=False)


class _ClaimIndex:
    """Parsed claims, cached per memory version and indexed by identifier, word and author.

    Validation runs on every auto-activating write, and parsing every memory
    each time made a write cost 44 ms at 5,000 memories. The refresh below
    is one version comparison per memory; only new or revised memories are
    parsed, and each check reads only the memories that share an identifier,
    a parameter word or an author.
    """

    def __init__(self) -> None:
        self.seen: dict[str, tuple[int, tuple, str, str]] = {}
        self.by_ident: dict[str, set[str]] = {}
        self.by_word: dict[str, set[str]] = {}
        self.by_author: dict[tuple[str, str], set[str]] = {}
        self.seq: int | None = None

    def _drop(self, mid: str) -> None:
        _, (ids, words, _), who, tenant = self.seen.pop(mid)
        for key, table in [(i, self.by_ident) for i in ids] + [(w, self.by_word) for w in words]:
            table.get(key, set()).discard(mid)
        self.by_author.get((tenant, who), set()).discard(mid)

    def _index_one(self, fabric: "MemoryFabric", mid: str) -> None:
        m = fabric.state.memories.get(mid)
        if mid in self.seen:
            self._drop(mid)
        if m is None:
            return
        parsed = claim(m.content)
        who = author(m)
        self.seen[mid] = (m.version, parsed, who, m.tenant_id)
        for ident in parsed[0]:
            self.by_ident.setdefault(ident, set()).add(mid)
        for word in parsed[1]:
            self.by_word.setdefault(word, set()).add(mid)
        self.by_author.setdefault((m.tenant_id, who), set()).add(mid)

    def refresh(self, fabric: "MemoryFabric") -> None:
        """Bring the index up to the log head: a full build once, then only what changed.

        After the first build it reads just the events since the last refresh
        and re-indexes the memories they created, revised or erased. A
        per-write scan of every memory made seeding 20,000 memories quadratic.
        """
        from .events import EventType

        head = fabric._seen_seq
        if self.seq is None:
            for mid in fabric.state.memories:
                self._index_one(fabric, mid)
            self.seq = head
            return
        if head == self.seq:
            return
        changed: set[str] = set()
        for event in fabric.log.read(since_seq=self.seq):
            if event.type in (EventType.MEMORY_CREATED, EventType.MEMORY_VERSIONED):
                body = event.payload.get("memory")
                if isinstance(body, dict) and body.get("id"):
                    changed.add(str(body["id"]))
            elif event.type == EventType.CONTENT_ERASED and event.payload.get("memory_id"):
                changed.add(str(event.payload["memory_id"]))
        for mid in changed:
            self._index_one(fabric, mid)
        self.seq = head

    def claim_of(self, mid: str) -> tuple:
        return self.seen[mid][1]


def _index(fabric: "MemoryFabric") -> _ClaimIndex:
    index = getattr(fabric, "_claim_index", None)
    if index is None:
        index = _ClaimIndex()
        fabric._claim_index = index  # type: ignore[attr-defined]
    index.refresh(fabric)
    return index


def _assess(fabric: "MemoryFabric", memory: Any, with_authority: bool) -> Assessment:
    from . import authority
    from .model import EXPOSABLE_STATES, WITHDRAWN_STATES

    memory_id = memory.id
    mine = claim(memory.content)
    ids, words, values = mine
    signals: dict[str, str] = {}
    if not ids or not values:
        return Assessment(memory_id, "unremarkable", {})
    me = author(memory)
    tenant = memory.tenant_id
    index = _index(fabric)
    memories = fabric.state.memories

    def track_record(who: str, before: int, exclude: str | None = None) -> bool:
        return any(m != exclude and m != memory_id and memories[m].created_at < before
                   and memories[m].lifecycle_state in EXPOSABLE_STATES
                   for m in index.by_author.get((tenant, who), ()))

    same_claim = set().union(*(index.by_ident.get(i, set()) for i in ids)) - {memory_id}
    for oid in same_claim:
        other = memories[oid]
        theirs = index.claim_of(oid)
        if other.tenant_id != tenant or not _same_claim(mine, theirs):
            continue
        if other.lifecycle_state in WITHDRAWN_STATES and theirs[2] == values:
            signals.setdefault("reasserts_corrected", oid)
        elif other.lifecycle_state in EXPOSABLE_STATES and theirs[2] and theirs[2] != values:
            # Established means older *and* by an author with a track record
            # (another usable memory) by now. Without the second condition an
            # earlier poison counted as established, and an honest author
            # correcting it was flagged (V1 dev: 8 of 30 honest updates).
            if (author(other) != me and other.created_at <= memory.created_at
                    and track_record(author(other), memory.created_at, exclude=oid)):
                signals.setdefault("contradicts_established", oid)
        elif (other.lifecycle_state in EXPOSABLE_STATES and theirs[2] == values
              and (not memory_id or fabric.source_root(oid) != fabric.source_root(memory_id))
              and author(other) != me):
            signals.setdefault("corroborated", oid)

    # Same kind of parameter on other equipment: share two content words.
    counts: dict[str, int] = {}
    for w in words:
        for oid in index.by_word.get(w, ()):
            counts[oid] = counts.get(oid, 0) + 1
    peers_values: list[float] = []
    for oid, shared in counts.items():
        if shared < 2 or oid == memory_id or oid in same_claim:
            continue
        other = memories[oid]
        if other.tenant_id != tenant or other.lifecycle_state not in EXPOSABLE_STATES:
            continue
        if _same_parameter(mine, index.claim_of(oid)):
            n = _number(index.claim_of(oid)[2])
            if n is not None:
                peers_values.append(n)

    value = _number(values)
    if value is not None and len(peers_values) >= MIN_COMPARABLE:
        median = statistics.median(peers_values)
        mad = statistics.median(abs(v - median) for v in peers_values) or 1e-9
        z = abs(value - median) / (1.4826 * mad)
        # A high z alone flagged honest unusual values (1.6x the usual top: V1
        # dev, 6 of 45). Implausible means far outside everything comparable:
        # beyond twice the largest, or below half the smallest, as well.
        beyond = value > 2 * max(peers_values) or value < 0.5 * min(peers_values)
        if z > OUTLIER_Z and beyond:
            signals["outlier"] = (f"{value:g} against a median of {median:g} over "
                                  f"{len(peers_values)} comparable claims (z={z:.1f})")

    if not track_record(me, memory.created_at):
        signals["new_source"] = me
    try:
        if with_authority and authority.of(fabric, memory_id).trust == authority.UNTRUSTED:
            signals["untrusted_origin"] = ",".join(authority.of(fabric, memory_id).reasons)
    except Exception:  # noqa: BLE001 - assessment never blocks on authority
        pass

    if any(s in signals for s in SUSPICIOUS):
        level = "suspicious"
    elif "corroborated" in signals:
        level = "corroborated"
    elif any(s in signals for s in PROVISIONAL):
        level = "provisional"
    else:
        level = "unremarkable"
    return Assessment(memory_id, level, signals)


def review_queue(fabric: "MemoryFabric") -> list[Assessment]:
    """Every exposable or candidate memory whose assessment is suspicious, worst first."""
    from .model import EXPOSABLE_STATES, LifecycleState

    out = [assess(fabric, m.id) for m in fabric.state.memories.values()
           if m.lifecycle_state in EXPOSABLE_STATES or m.lifecycle_state is LifecycleState.CANDIDATE]
    return [a for a in out if a.suspicious]


def summary(a: Assessment) -> dict[str, Any]:
    return {"memory_id": a.memory_id, "level": a.level, "signals": dict(a.signals)}
