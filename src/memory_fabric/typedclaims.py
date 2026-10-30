"""Typed claims: catch a free-text contradiction without a model call.

The built-in claim check reads identifiers and values ("P-14 relief is
12 bar"), so a plain sentence is never checked: "the east wing is not safe to
enter" sails past "the east wing is safe to enter". `ModelClaimChecker` catches
it at a model call per write (C3). This reads each claim once, when it is
written, as a small typed proposition:

- **what it is about**: its content words, reduced to a root so "covered",
  "coverage" and "covers" agree;
- **polarity**: flipped by negation ("not", "never", "no", "no longer") and by
  a short list of opposites ("banned"/"prohibited" against "allowed"/
  "permitted", "broken" against "works", "closed" against "open"), and by an
  "un-", "dis-", "in-" or "non-" prefix when the bare word is in the other claim.

Two claims contradict when one's content words contain all of the other's
(they say the same thing about the same subject, one perhaps with an extra
detail), they share at least two, and their polarities differ. That last
containment rule is what keeps "the **west** wing is not safe" from being
held against "the **east** wing is safe": each has a word the other lacks.

    from memory-fabric import MemoryFabric
    from memory_fabric.typedclaims import TypedClaimChecker
    fabric = MemoryFabric("store.db", claim_checker=TypedClaimChecker())

It plugs into the same hook as `ModelClaimChecker`, runs only on writes the
built-in rules do not read, compares only against established memories by
other authors, and a hit holds the write for review: it is never deleted.
Measured on a held-out world before any default changed
(`research/prereg/o1-typed-claims.md`).
"""

from __future__ import annotations

__stability__ = "beta"

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover
    from .fabric import MemoryFabric

NEGATIONS = frozenset("not no never cannot without".split())
# "any more" / "anymore" only strengthen a negation ("no night shift any more"); they add none.
NEGATION_PHRASES = ("no longer", "will not", "won't", "can't", "isn't", "aren't",
                    "doesn't", "don't", "wasn't", "weren't", "hasn't", "haven't")
# word -> (canonical word, flips polarity)
OPPOSITES: dict[str, tuple[str, bool]] = {
    "banned": ("permit", True), "ban": ("permit", True), "prohibited": ("permit", True),
    "prohibit": ("permit", True), "forbidden": ("permit", True), "barred": ("permit", True),
    "allowed": ("permit", False), "allow": ("permit", False), "permitted": ("permit", False),
    "broken": ("work", True), "faulty": ("work", True), "dead": ("work", True), "failed": ("work", True),
    "works": ("work", False), "working": ("work", False), "functional": ("work", False),
    "closed": ("open", True), "shut": ("open", True), "open": ("open", False),
    "absent": ("present", True), "present": ("present", False),
    "off": ("on", True),
}
STOP = frozenset(
    "the a an is are was were be been being it its of for to in on at and or do does did has have had "
    "this that these those there here by with from into onto as gets get got any some every each "
    "will would should could may might must can also only just now still again until further "
    "any more anymore".split())
PREFIXES = ("non", "dis", "un", "in")


def _stem(word: str) -> str:
    w = word.lower().strip("'")
    for suffix, keep in (("ing", 5), ("age", 5), ("ed", 4), ("es", 4), ("s", 3)):
        if len(w) > keep and w.endswith(suffix) and not w.endswith("ss"):
            w = w[: -len(suffix)]
            break
    return re.sub(r"(.)\1$", r"\1", w)   # permitt -> permit, staff -> staf: one form for both


@dataclass(frozen=True)
class Proposition:
    words: frozenset[str]
    negative: bool


def proposition(text: str) -> Proposition:
    """The first clause of `text` as content words and a polarity."""
    first = re.split(r";|\s+-\s+|\.\s|\bbut\b|\band\b", text.strip(), maxsplit=1)[0].lower()
    negative = False
    for phrase in NEGATION_PHRASES:
        if phrase in first:
            negative = not negative
            first = first.replace(phrase, " ")
    words = set()
    for raw in re.findall(r"[a-z][a-z0-9-]*", first):
        if raw in NEGATIONS:
            negative = not negative
            continue
        if raw in OPPOSITES:
            canon, flips = OPPOSITES[raw]
            negative ^= flips
            words.add(canon)
            continue
        if raw in STOP or len(raw) < 3:
            continue
        words.add(_stem(raw))
    return Proposition(frozenset(words), negative)


def _align(a: Proposition, b: Proposition) -> tuple[Proposition, Proposition]:
    """Read a prefix as negation where the bare word is in the other claim: unheated ~ not heated."""
    def fix(p: Proposition, other: frozenset[str]) -> Proposition:
        words, neg = set(p.words), p.negative
        for w in p.words:
            for pre in PREFIXES:
                if w.startswith(pre) and w[len(pre):] in other and w not in other:
                    words.discard(w)
                    words.add(w[len(pre):])
                    neg = not neg
                    break
        return Proposition(frozenset(words), neg)
    return fix(a, b.words), fix(b, a.words)


def contradicts(new: str, old: str) -> bool:
    """True when the two say opposite things about the same subject."""
    a, b = _align(proposition(new), proposition(old))
    shared = a.words & b.words
    same_subject = a.words <= b.words or b.words <= a.words
    return same_subject and len(shared) >= 2 and a.negative != b.negative


class TypedClaimChecker:
    """A `claim_checker` (`MemoryFabric(claim_checker=…)`) that needs no model."""

    def __init__(self, k: int = 10) -> None:
        self.k = k
        self.calls = 0

    def check(self, fabric: "MemoryFabric", agent_id: str, content: str, tenant_id: str) -> str | None:
        """The id of an established memory by another author this claim contradicts, or None."""
        from .conflicts import author
        from .model import EXPOSABLE_STATES

        self.calls += 1
        for mid, _ in fabric.lexical.search(content, k=self.k * 4, min_relevance=0.0):
            m: Any = fabric.state.memories.get(mid)
            if (m is None or m.tenant_id != tenant_id or m.lifecycle_state not in EXPOSABLE_STATES
                    or author(m) == agent_id or not isinstance(m.content, str)):
                continue
            if contradicts(content, m.content):
                return str(m.id)
        return None
