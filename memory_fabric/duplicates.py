"""Recognising a re-ingested document.

## The gap this closes, and why it was the last one standing

[P3](../research/results/p3-correction-propagation.md) measured four
propagation rules against an oracle and found the product already correct on
three families out of four. The whole residual — **100% of it** — was one case:
a contractor bulletin withdrawn as wrong, then re-ingested months later from a
shared drive under its own id.

Provenance records two sources, because there *were* two ingestions. Root
identity says the copy is independent evidence. Parent edges say the copy is
independent evidence. Both are right about the provenance and wrong about the
evidence, and every rule tested — including `_group_by_root`, which exists to
stop copies counting as corroboration — kept both votes.

So the missing thing is not a propagation rule. It is **identity**: deciding, at
write time, that this content has been seen before.

## Why a copy is not a parent

The obvious implementation is to record the copy as derived from the original.
It is wrong in a way that would have looked like it worked: `_group_by_root`
deliberately **spares** a memory that is derivation-related to something
already kept, because a premise and the conclusion drawn from it are not
copies. A copy recorded as a child would therefore be exempted from the
grouping that exists to collapse it.

A copy gets its own relation. `source_root` resolves through it, so copies share
a grouping key; `_derivation_related` does not, so they collapse rather than
being spared; and retraction follows it, so withdrawing the original withdraws
the re-ingestion.

## The rule is subset containment, and measurement chose it

The first version of this module used Jaccard overlap above 0.75. **Measured on
real corpora, that rule is actively wrong**, and the numbers are why this
docstring is not the one I first wrote:

| pair | Jaccard | containment |
|---|---|---|
| a true re-ingestion (`propagation_v1`, 4 cases) | **0.722** | **1.000** |
| the worst of 152,640 near-miss pairs (`relevance_v2`) | **0.800** | 0.889 |
| a derived restatement of the original | 0.571 | 0.889 |

A copy *adds* a filing note, so Jaccard penalises it for growing; a near-miss
differs by one facet token out of nine, so Jaccard barely notices. The orders
cross: **any Jaccard threshold catching real copies catches near-misses
first.** That would have put two memories about different sites under one
source root and called it deduplication.

Containment separates, so the rule is the strongest form of it with no
threshold to tune: **the shorter memory's content terms are a subset of the
longer's, and the two are within a factor of two in length.** A near-miss can
never satisfy the subset condition, because the token it differs on is absent
from the other side. The length guard stops a short generic memory being
declared a copy of a long one that happens to contain its words.

`distribution()` reports both measures for any corpus, so the Jaccard failure
stays checkable rather than remembered. The last threshold this project
defended as "the midpoint of a bimodal gap" had overlapping tails, and the
overlap was only visible once something printed it
(`research/results/p2-context-sufficiency.md` §7).

## The direction of error, chosen deliberately

A missed copy costs what P3 measured: two votes for one piece of evidence, and
a withdrawal that does not reach its restatement. A false match costs a memory
being grouped with something it is not — which `_group_by_root` already does to
near-identical independent observations, and which its own docstring names as
the price of not doing content deduplication. The second is recoverable from
the log; the first is a wrong answer at full confidence. Subset containment
makes false matches very unlikely and missed copies merely possible, which is
the right way round.
"""

from __future__ import annotations

__stability__ = "stable"

import re
import unicodedata
from dataclasses import dataclass
from typing import Iterable, Mapping, Sequence

from .vectors import _STOPWORDS

MIN_TERMS = 4
"""Below this, containment is not evidence of anything.

A three-term memory is a subset of a great many longer ones. Short content is
where any similarity rule is least reliable, so it is excluded rather than
thresholded differently.
"""

MAX_LENGTH_RATIO = 2.0
"""How much longer the copy may be than the original, in content terms.

A header, a filing note or a "(copy)" marker does not double a document's
length; the measured re-ingestions sit at 1.38. Without this, a four-term
memory whose words all appear in a forty-term one would be declared a copy of
it.
"""

_TOKEN = re.compile(r"[a-z0-9]+(?:[-.][a-z0-9]+)*")


def canonical(content: str) -> str:
    """The text with encoding noise removed, and nothing else.

    A withdrawn document pasted back in from a PDF arrives with soft hyphens,
    zero-width spaces, ligatures and non-ASCII hyphens. Each of those split a
    term, so the copy no longer contained the original and came back as active,
    independent evidence (found 2026-10-16: 4 of 7 encodings evaded). NFKC folds
    ligatures and full-width forms; format characters (Unicode category Cf) are
    dropped; every dash becomes "-". None of these can merge two distinct words,
    which is the error this module is built to avoid. Look-alike letters are
    deliberately not mapped here.
    """
    text = unicodedata.normalize("NFKC", content)
    return "".join(
        "-" if unicodedata.category(ch) == "Pd" else ch
        for ch in text if unicodedata.category(ch) != "Cf"
    )


def terms(content: str) -> frozenset[str]:
    """Content terms, identifiers kept whole.

    The same tokenisation `chains` uses, and for the same reason: "CB-9" is the
    document's name, and splitting it into "cb" and "9" loses exactly the token
    that identifies it. Applied to `canonical(content)`.
    """
    return frozenset(
        t for t in _TOKEN.findall(canonical(content).lower()) if t not in _STOPWORDS
    )


def containment(left: frozenset[str], right: frozenset[str]) -> float:
    """Share of the *shorter* side's terms present in the other."""
    if not left or not right:
        return 0.0
    return len(left & right) / min(len(left), len(right))


def jaccard(left: frozenset[str], right: frozenset[str]) -> float:
    """Reported by `distribution()` only. Measured not to separate copies."""
    union = left | right
    return len(left & right) / len(union) if union else 0.0


def is_copy(left: str, right: str) -> bool:
    """Whether these two are one document ingested twice.

    Subset containment plus a length guard. No threshold: either every content
    term of the shorter appears in the longer, or they are not the same
    document.
    """
    a, b = terms(left), terms(right)
    if len(a) < MIN_TERMS or len(b) < MIN_TERMS:
        return False
    shorter, longer = (a, b) if len(a) <= len(b) else (b, a)
    if len(longer) > len(shorter) * MAX_LENGTH_RATIO:
        return False
    return shorter <= longer


@dataclass(frozen=True)
class Match:
    memory_id: str
    score: float
    """Containment, for the audit record. Always 1.0 under the current rule;
    carried so a future looser rule cannot change what is logged."""


def find_copy(
    content: str,
    existing: Mapping[str, str],
    *,
    exclude: Iterable[str] = (),
) -> Match | None:
    """The existing memory this content is a copy of, or None.

    Ties break on the lexicographically smallest id, so the choice cannot
    depend on dict order — the same reason `source_root` takes the smallest of
    several roots. A copy-of relation that varied by insertion order would make
    grouping non-deterministic, which is the bug that rule exists to avoid.
    """
    skip = set(exclude)
    hits = [
        memory_id for memory_id, other in existing.items()
        if memory_id not in skip and is_copy(content, other)
    ]
    if not hits:
        return None
    chosen = min(hits)
    return Match(
        memory_id=chosen,
        score=round(containment(terms(content), terms(existing[chosen])), 4),
    )


def distribution(contents: Sequence[str]) -> dict[str, float | int]:
    """Pairwise separation under both measures, for checking the rule on data.

    Exists because the first version of this module used a Jaccard threshold
    that measurement showed to be ordered the wrong way round, and nothing
    would have revealed that without printing it.
    """
    tsets = [terms(c) for c in contents]
    rows: list[tuple[float, float, bool]] = []
    for i, left in enumerate(tsets):
        for j in range(i + 1, len(tsets)):
            right = tsets[j]
            rows.append((jaccard(left, right), containment(left, right),
                         is_copy(contents[i], contents[j])))
    if not rows:
        return {"pairs": 0}
    copies = [r for r in rows if r[2]]
    others = [r for r in rows if not r[2]]
    return {
        "pairs": len(rows),
        "copies": len(copies),
        "min_copy_jaccard": round(min((r[0] for r in copies), default=0.0), 4),
        "max_other_jaccard": round(max((r[0] for r in others), default=0.0), 4),
        "min_copy_containment": round(min((r[1] for r in copies), default=0.0), 4),
        "max_other_containment": round(max((r[1] for r in others), default=0.0), 4),
    }


class CopyIndex:
    """A bounded candidate set for the subset test.

    The first implementation compared incoming content against every memory
    held. Measured, that costs **0.47 ms a write at 100 memories, 3.3 ms at
    1,000 and 32.4 ms at 10,000** against 0.19 ms with the check off -- a 168x
    write cost, growing linearly, which makes a store of any size unusable and
    makes the default indefensible.

    The index narrows the candidates without weakening the rule, which needs
    both directions of the subset test covered:

    * **incoming is the shorter side** (`I` subset of `C`). Every term of `I`
      is then in `C`, so every candidate appears in `postings[t]` for every
      `t` in `I`. Taking the *smallest* of those posting lists is a valid
      superset and usually a tiny one, because the rarest term in a sentence
      naming a document is the document's name.
    * **incoming is the longer side** (`C` subset of `I`). A candidate need not
      contain any particular term of `I`, so the first index cannot find it.
      But every term of `C` is in `I`, so if each memory is indexed under a
      few of *its own* terms, all of those anchors are in `I` and the
      candidate is reachable from any of them.

    Both are exact. The index returns a superset and `is_copy` still decides,
    so a bug here can only cost time, never correctness -- which is why the
    exhaustive path is kept as `find_copy` and tested against this one.
    """

    ANCHORS = 1
    """How many of its own terms each memory is indexed under: its rarest, at write time.

    One is exact. If a stored memory C is contained in the incoming text I,
    every term of C is in I, its anchor included, so C is reachable from
    `anchors[anchor(C)]`. More anchors cannot find anything one misses; they
    only make the buckets longer. Three was the first choice, and on a store
    of near-identical notes ("The purge time for P1 is 40 s.") every memory's
    third anchor tied on a common word, put the whole store in one bucket,
    and made each write scan all of it (5,000 notes: ~29 ms a write).
    """

    def __init__(self) -> None:
        self.postings: dict[str, set[str]] = {}
        self.anchors: dict[str, set[str]] = {}
        self.terms: dict[str, frozenset[str]] = {}

    def add(self, memory_id: str, content: str) -> None:
        # Replace, never accumulate: a revision's old terms would otherwise
        # stay reachable, and an erased memory's -- whose marker is too short
        # to index -- would stay in memory after the erasure.
        self.remove(memory_id)
        tokens = terms(content)
        if len(tokens) < MIN_TERMS:
            return
        self.terms[memory_id] = tokens
        for token in tokens:
            self.postings.setdefault(token, set()).add(memory_id)
        # Rarest first, by the posting lists as they stand now.
        rarest = sorted(tokens, key=lambda t: (len(self.postings.get(t, ())), t))
        for token in rarest[: self.ANCHORS]:
            self.anchors.setdefault(token, set()).add(memory_id)

    def remove(self, memory_id: str) -> None:
        """Forget a memory's terms entirely. For erasure and deletion only.

        Withdrawn memories stay in the index on purpose: re-ingesting a
        quarantined or deprecated document must still be recognised as a
        copy. An erased one has no content left to be a copy of, and its
        term set is derived from the plaintext erasure destroyed.
        """
        tokens = self.terms.pop(memory_id, None)
        if tokens is None:
            return
        for token in tokens:
            for table in (self.postings, self.anchors):
                bucket = table.get(token)
                if bucket is not None:
                    bucket.discard(memory_id)
                    if not bucket:
                        del table[token]

    def candidates(self, content: str, tokens: frozenset[str] | None = None) -> set[str]:
        tokens = terms(content) if tokens is None else tokens
        if len(tokens) < MIN_TERMS:
            return set()
        # Direction 1: the smallest posting list among the incoming terms.
        lists = [self.postings.get(t, set()) for t in tokens]
        smallest = min(lists, key=len) if lists else set()
        # Direction 2: anything anchored on a term the incoming content has.
        out = set(smallest)
        for token in tokens:
            out |= self.anchors.get(token, set())
        return out

    def find(self, content: str, *, exclude: Iterable[str] = ()) -> Match | None:
        skip = set(exclude)
        # Tokenised once. It was re-tokenised for every candidate, which on a
        # store of near-duplicates was 90% of a write's time and grew with
        # the store (5,000 near-identical memories: ~29 ms a write).
        incoming = terms(content)
        hits = [
            memory_id
            for memory_id in self.candidates(content, incoming)
            if memory_id not in skip and memory_id in self.terms
            and _is_copy_terms(incoming, self.terms[memory_id])
        ]
        if not hits:
            return None
        chosen = min(hits)
        return Match(
            memory_id=chosen,
            score=round(containment(incoming, self.terms[chosen]), 4),
        )


def _is_copy_terms(a: frozenset[str], b: frozenset[str]) -> bool:
    """`is_copy` on already-tokenised sides, so the index does not re-tokenise."""
    if len(a) < MIN_TERMS or len(b) < MIN_TERMS:
        return False
    shorter, longer = (a, b) if len(a) <= len(b) else (b, a)
    if len(longer) > len(shorter) * MAX_LENGTH_RATIO:
        return False
    return shorter <= longer
