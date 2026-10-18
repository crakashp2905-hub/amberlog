"""Contradicting memories, surfaced instead of ranked away (G4b).

## The weakness this answers

G4 measured it on real models: **before a poison is detected, retrieval
ranked it above the honest note in 35 of 40 poisoned questions.** A plain
lexical store did so in 20 of 40, and the model followed the first note. The
store had both memories, and nothing in it noticed that they disagreed, so
lexical similarity decided which one the agent saw first. Retraction fixes
that later. A governed store cannot rely on "later" alone.

Every attack in that benchmark has the same shape before detection. A
poisoned value, a paraphrased injection that slips past the pattern screen,
and a re-ingested wrong bulletin all assert **a different value for the same
claim** as an existing memory. That shape is detectable without knowing which
side is wrong.

## The rule, fixed in advance rather than tuned

Two memories contradict when:

- they name the **same identifiers** (tokens mixing letters and digits, such
  as `P7` or `E01`): the same subject;
- the shorter one's content words are at least 80% contained in the other's:
  the same kind of claim;
- the numbers they assert **differ**: a different value.

A different protocol is a different identifier, so it is not a conflict. The
same sentence with the same number is a copy, which `duplicates.py` handles.

A known false positive, stated: two claims about the same identifier that
differ in one content word and in their number (P7's centrifuge and P7's
incubator) look like one claim with two values.

## What retrieval does with a conflict (`annotate`)

The contradicting notes are placed together and flagged. Nothing is hidden,
because the store does not know which side is wrong:

- `mode="flag"`: in ranked order, with each member marked as disputed;
- `mode="incumbent"`: the earliest-written member first, and later ones
  marked as newer claims that contradict an earlier note. This bets that the
  established claim is the honest one. **An attacker who writes first wins
  that bet**, which G4b measures rather than assumes.

Notes by the same author are not a conflict: an author's later claim about
the same thing is a correction (`revise` is the governed way to make one).
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any, Sequence

from .vectors import _STOPWORDS

if TYPE_CHECKING:  # pragma: no cover
    from .model import Memory

MIN_CONTAINMENT = 0.8
_TOKEN = re.compile(r"[a-z0-9]+(?:\.[0-9]+)?")


def claim(content: str) -> tuple[frozenset[str], frozenset[str], frozenset[str]]:
    """(identifiers, content words, numeric values) of a memory's text."""
    identifiers, words, values = set(), set(), set()
    for token in _TOKEN.findall(content.lower()):
        has_digit = any(ch.isdigit() for ch in token)
        has_alpha = any(ch.isalpha() for ch in token)
        if has_digit and has_alpha:
            identifiers.add(token)
        elif has_digit:
            values.add(token)
        elif token not in _STOPWORDS and len(token) > 1:
            words.add(token)
    return frozenset(identifiers), frozenset(words), frozenset(values)


def contradicts(left: str, right: str) -> bool:
    li, lw, lv = claim(left)
    ri, rw, rv = claim(right)
    if not li or li != ri or not lv or not rv or lv == rv:
        return False
    shorter, longer = (lw, rw) if len(lw) <= len(rw) else (rw, lw)
    if not shorter:
        return False
    return len(shorter & longer) / len(shorter) >= MIN_CONTAINMENT


def author(memory: "Memory") -> str:
    """Who asserted it. For an import, the original author, not the importing agent.

    Every import is written by the recipient agent, so without this an honest
    note and a poison imported from the same site look like one author
    correcting themselves (found on G4b's dev world before any model run).
    """
    origin = memory.context.get("federation")
    if isinstance(origin, dict) and isinstance(origin.get("agent"), str):
        return f"{origin.get('store', '')}/{origin['agent']}"
    return memory.provenance.created_by


def find_conflicts(memories: Sequence["Memory"]) -> list[list["Memory"]]:
    """Groups of mutually connected contradicting memories, by different authors."""
    ids = [m.id for m in memories]
    by_id = {m.id: m for m in memories}
    parent = {i: i for i in ids}

    def find(i: str) -> str:
        while parent[i] != i:
            i = parent[i]
        return i

    for a in range(len(ids)):
        for b in range(a + 1, len(ids)):
            left, right = by_id[ids[a]], by_id[ids[b]]
            if author(left) == author(right):
                continue
            if contradicts(left.content, right.content):
                parent[find(ids[a])] = find(ids[b])
    groups: dict[str, list["Memory"]] = {}
    for i in ids:
        groups.setdefault(find(i), []).append(by_id[i])
    return [g for g in groups.values() if len(g) > 1]


DISPUTED = ("[DISPUTED: the store holds notes that give different values for this; "
            "it has not resolved which is right]")
NEWER = "[NEWER CLAIM: contradicts an earlier note and has not been confirmed]"


def annotate(memories: Sequence["Memory"], *, mode: str = "flag",
             created_seq: dict[str, int] | None = None) -> list[str]:
    """The notes' texts, with every contradiction placed together and flagged."""
    if mode not in ("flag", "incumbent"):
        raise ValueError("mode must be 'flag' or 'incumbent'")
    groups = find_conflicts(memories)
    member = {m.id: n for n, g in enumerate(groups) for m in g}
    order = created_seq or {}
    out: list[str] = []
    placed: set[int] = set()
    for memory in memories:
        n = member.get(memory.id)
        if n is None:
            out.append(memory.content)
            continue
        if n in placed:
            continue
        placed.add(n)
        group: list[Any] = list(groups[n])
        if mode == "incumbent":
            group.sort(key=lambda m: order.get(m.id, 0))
            out.append(f"{DISPUTED} {group[0].content}")
            out.extend(f"{DISPUTED} {NEWER} {m.content}" for m in group[1:])
        else:
            out.extend(f"{DISPUTED} {m.content}" for m in group)
    return out
