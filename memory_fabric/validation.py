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
| `conflicts_with_pending` | **under review** (a candidate), and another candidate by another author gives another value for this claim; neither is established yet, so a reviewer approving a batch must decide between them | suspicious |
| `outlier` | its value is far outside what the store holds for this kind of parameter on other equipment: robust z > 3.5 **and** beyond twice the largest or half the smallest of at least 5 comparable claims | suspicious |
| `new_source` | its author has no validated memory older than this one | provisional |
| `untrusted_origin` | its origin-bound authority is untrusted (tool output, import, web) | provisional |
| `revises_validated` | its own author restates a fact **someone else validated** with another value, and nobody has validated the new one | provisional |
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

SUSPICIOUS = ("reasserts_corrected", "contradicts_established", "conflicts_with_pending",
              "outlier")
PROVISIONAL = ("new_source", "untrusted_origin", "revises_validated")
OUTLIER_Z = 3.5
MIN_COMPARABLE = 5
PEER_SAMPLE = 256
"""Comparable claims the outlier check reads, newest first."""
PEER_SCAN = 1024
"""At most this many memories are looked at to find them."""


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
    if len(words_a & words_b) < max(1, need):
        return False
    # A word each side has and the other lacks names a different context:
    # "tug-1 requires 2.4 m at the coastal site" and "... at the inland site"
    # are two facts, not one fact with two values. One side may add detail
    # ("relief pressure" against "relief"), as in typed claims (O1).
    return words_a <= words_b or words_b <= words_a


def _same_parameter(a: tuple, b: tuple) -> bool:
    """Another identifier, but the same kind of parameter: two shared content words."""
    ids_a, words_a, _ = a
    ids_b, words_b, _ = b
    return bool(ids_a) and bool(ids_b) and ids_a != ids_b and len(words_a & words_b) >= 2


def restatements(fabric: "MemoryFabric", memory: Any) -> list[str]:
    """Usable memories elsewhere that state this version's claim with the same value.

    Called before a version is corrected or withdrawn: those are the notes the
    correction leaves behind. Nothing links a note that merely repeats a value
    ("measured again: P7 at 41 bar") to the fact it repeats, so without this a
    correction never reaches it and retrieval keeps serving the old value (GME
    matrix, research/results/gme-matrix.md). Same tenant, same claim
    (`_same_claim`), identical values; the memory itself and its own
    descendants excluded, since lineage already handles those.
    """
    from .model import EXPOSABLE_STATES

    mine = claim(memory.content)
    ids, _, values = mine
    if not ids or not values:
        return []
    index = _index(fabric)
    memories = fabric.state.memories
    own = {memory.id}
    frontier = [memory.id]
    while frontier:
        for child in fabric.state.children.get(frontier.pop(), ()):
            if child not in own:
                own.add(child)
                frontier.append(child)
    out = []
    for oid in sorted(set().union(*(index.by_ident.get(i, set()) for i in ids)) - own):
        other = memories.get(oid)
        if (other is None or other.tenant_id != memory.tenant_id
                or other.lifecycle_state not in EXPOSABLE_STATES):
            continue
        theirs = index.claim_of(oid)
        if theirs[2] == values and _same_claim(mine, theirs):
            out.append(oid)
    return out


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


def _newer_version_of(memory: Any, other: Any) -> bool:
    """Whether `memory` is a later version of the same original memory `other` copied.

    Federation records the root (original store and memory) and the root's
    version on every import, re-shares included, so "the origin revised its
    own memory" is a fact on both copies, not an inference from text or
    authorship. Without a root version (an import from before 0.14.0) the
    answer is no, and the write is held as before.
    """
    def root(m: Any) -> tuple[Any, Any, Any]:
        fed = (m.context or {}).get("federation")
        r = fed.get("root") if isinstance(fed, dict) else None
        return (r.get("store"), r.get("memory_id"), r.get("version")) if isinstance(r, dict) else (None, None, None)

    (s1, m1, v1), (s2, m2, v2) = root(memory), root(other)
    return (s1 is not None and m1 is not None and (s1, m1) == (s2, m2)
            and isinstance(v1, int) and isinstance(v2, int) and v1 > v2)


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
        # Insertion-ordered (a dict used as an ordered set), so the outlier
        # check can read the newest comparable claims first without sorting.
        self.by_word: dict[str, dict[str, None]] = {}
        self.by_author: dict[tuple[str, str], set[str]] = {}
        self.vouched: dict[str, set[str]] = {}
        """memory id -> actors who validated it, from the log, kept incrementally."""
        self.seq: int | None = None
        self._numbers: dict[str, tuple[int, float | None]] = {}

    def _drop(self, mid: str) -> None:
        _, (ids, words, _), who, tenant = self.seen.pop(mid)
        for ident in ids:
            self.by_ident.get(ident, set()).discard(mid)
        for word in words:
            self.by_word.get(word, {}).pop(mid, None)
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
            self.by_word.setdefault(word, {})[mid] = None
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
            for event in fabric.log.read():
                self._note_validation(event)
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
            self._note_validation(event)
        for mid in changed:
            self._index_one(fabric, mid)
        self.seq = head

    def _note_validation(self, event: Any) -> None:
        from .events import EventType

        p = event.payload
        if (event.type == EventType.LIFECYCLE_CHANGED and p.get("to") == "active"
                and p.get("reason") == "validated" and p.get("actor") and p.get("memory_id")):
            self.vouched.setdefault(str(p["memory_id"]), set()).add(str(p["actor"]))

    def claim_of(self, mid: str) -> tuple:
        return self.seen[mid][1]

    def number_of(self, mid: str) -> float | None:
        """The claim's single value, if it has exactly one; cached per version."""
        entry = self.seen[mid]
        cached = self._numbers.get(mid)
        if cached is not None and cached[0] == entry[0]:
            return cached[1]
        value = _number(entry[1][2])
        self._numbers[mid] = (entry[0], value)
        return value


def _index(fabric: "MemoryFabric") -> _ClaimIndex:
    index = getattr(fabric, "_claim_index", None)
    if index is None:
        index = _ClaimIndex()
        fabric._claim_index = index  # type: ignore[attr-defined]
    index.refresh(fabric)
    return index


def _validated_by_other(index: "_ClaimIndex", memory_id: str, who: str) -> str | None:
    """An actor, other than `who`, who validated this memory, if any.

    Read from the claim index, which follows the log incrementally. Reading
    each memory's audit trail instead scanned the whole log per check, and
    the full suite went from 6 to over 20 minutes.
    """
    others = sorted(index.vouched.get(memory_id, set()) - {who}) if memory_id else []
    return others[0] if others else None


def _assess(fabric: "MemoryFabric", memory: Any, with_authority: bool) -> Assessment:
    from . import authority
    from .model import EXPOSABLE_STATES, WITHDRAWN_STATES, LifecycleState

    memory_id = memory.id
    # Reviewing an existing candidate (not checking a write in flight).
    reviewing = (with_authority and memory_id in fabric.state.memories
                 and memory.lifecycle_state is LifecycleState.CANDIDATE)
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
            # Restating a withdrawn value is suspicious -- unless this is a newer
            # version of the very memory that was withdrawn, from its origin: the
            # origin reverting its own correction (56 -> 79 -> 56). Holding that
            # left every recipient serving nothing for the fact (S1 at HEAD:
            # convergence 1.00 -> 0.70). A value withdrawn on any other memory,
            # or re-sent at the same or an older version, stays held.
            if not _newer_version_of(memory, other):
                signals.setdefault("reasserts_corrected", oid)
        elif other.lifecycle_state in EXPOSABLE_STATES and theirs[2] and theirs[2] != values:
            # An author changing its own fact is an update, not a conflict, but
            # if a reviewer had vouched for the old value, the new one has not
            # been vouched for. A compromised established account is exactly
            # this case (LIMITATIONS: "can change its own facts"), so it is
            # marked provisional until someone validates it, and a gate rule
            # can refuse it (`ToolRule.refuse_provisional`).
            if (author(other) == me and other.created_at <= memory.created_at
                    and (vouched := _validated_by_other(index, oid, me))
                    and not _validated_by_other(index, memory_id, me)):
                signals.setdefault("revises_validated", f"{oid} validated by {vouched}")
            # Established means older *and* by an author with a track record
            # (another usable memory) by now. Without the second condition an
            # earlier poison counted as established, and an honest author
            # correcting it was flagged (V1 dev: 8 of 30 honest updates).
            if (author(other) != me and other.created_at <= memory.created_at
                    and track_record(author(other), memory.created_at, exclude=oid)):
                signals.setdefault("contradicts_established", oid)
        elif (reviewing and other.lifecycle_state is LifecycleState.CANDIDATE
              and theirs[2] and theirs[2] != values and author(other) != me):
            # Found by the staging run: a reviewer approving a batch of new
            # writes let a contradiction through, because the true fact was
            # itself still pending, so nothing was "established" to contradict.
            # Review only: on the write path a held poison is a candidate too,
            # and flagging every honest correction of it would hold the
            # correction as well.
            signals.setdefault("conflicts_with_pending", oid)
        elif (other.lifecycle_state in EXPOSABLE_STATES and theirs[2] == values
              and (not memory_id or fabric.source_root(oid) != fabric.source_root(memory_id))
              and author(other) != me):
            signals.setdefault("corroborated", oid)

    # Same kind of parameter on other equipment: share two content words.
    # The newest PEER_SAMPLE comparable claims, read newest first from the
    # rarest word's list, with at most PEER_SCAN looked at. Counting every
    # memory sharing a word made each write linear in the store: 38 ms a
    # write at 4,000 memories, most of it here, for a median that a few
    # hundred recent peers estimate as well.
    peers_values: list[float] = []
    looked: set[str] = set()
    value = _number(values)
    # The peers only matter for the outlier test, which needs this claim to
    # have one value; without one there is nothing to compare and no scan.
    for w in (sorted(words, key=lambda w: (len(index.by_word.get(w, ())), w))
              if value is not None else ()):
        for oid in reversed(index.by_word.get(w, {})):
            if oid in looked:
                continue
            looked.add(oid)
            if oid != memory_id and oid not in same_claim:
                n = index.number_of(oid)
                if n is not None and len(index.claim_of(oid)[1] & words) >= 2:
                    other = memories[oid]
                    if (other.tenant_id == tenant and other.lifecycle_state in EXPOSABLE_STATES
                            and _same_parameter(mine, index.claim_of(oid))):
                        peers_values.append(n)
            if len(peers_values) >= PEER_SAMPLE or len(looked) >= PEER_SCAN:
                break
        if len(peers_values) >= PEER_SAMPLE or len(looked) >= PEER_SCAN:
            break

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
