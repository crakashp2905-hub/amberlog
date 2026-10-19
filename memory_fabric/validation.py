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


def _had_track_record(memories: list, who: str, before: int, exclude: str | None = None) -> bool:
    """Whether `who` has another usable memory written before `before`."""
    from .model import EXPOSABLE_STATES

    return any(author(m) == who and m.id != exclude and m.created_at < before
               and m.lifecycle_state in EXPOSABLE_STATES for m in memories)


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
    from . import authority
    from .model import EXPOSABLE_STATES, WITHDRAWN_STATES

    memory = fabric.state.memories[memory_id]
    mine = claim(memory.content)
    ids, _, values = mine
    signals: dict[str, str] = {}
    if not ids or not values:
        return Assessment(memory_id, "unremarkable", {})
    me = author(memory)

    others = [m for m in fabric.state.memories.values()
              if m.id != memory_id and m.tenant_id == memory.tenant_id]
    peers_values: list[float] = []
    for other in others:
        theirs = claim(other.content)
        if _same_claim(mine, theirs):
            if other.lifecycle_state in WITHDRAWN_STATES and theirs[2] == values:
                signals.setdefault("reasserts_corrected", other.id)
            elif other.lifecycle_state in EXPOSABLE_STATES and theirs[2] and theirs[2] != values:
                # Established means older *and* written by an author with a
                # track record (another usable memory) by now. Without the second condition an
                # earlier poison counted as established, and an honest author
                # correcting it was flagged (V1 dev: 8 of 30 honest updates).
                if (author(other) != me and other.created_at <= memory.created_at
                        and _had_track_record(others, author(other), memory.created_at,
                                              exclude=other.id)):
                    signals.setdefault("contradicts_established", other.id)
            elif (other.lifecycle_state in EXPOSABLE_STATES and theirs[2] == values
                  and fabric.source_root(other.id) != fabric.source_root(memory_id)
                  and author(other) != me):
                signals.setdefault("corroborated", other.id)
        elif other.lifecycle_state in EXPOSABLE_STATES and _same_parameter(mine, theirs):
            n = _number(theirs[2])
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

    track = [m for m in others if author(m) == me and m.created_at < memory.created_at
             and m.lifecycle_state in EXPOSABLE_STATES]
    if not track:
        signals["new_source"] = me
    try:
        if authority.of(fabric, memory_id).trust == authority.UNTRUSTED:
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
