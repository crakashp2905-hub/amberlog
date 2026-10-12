"""Reordering a fused candidate pool, without a model and without a weight.

## Why this exists

Five measurements say the same thing: **do not fuse a weak arm into a strong
one.** SciFact — fusing a hashed vector arm into lexical costs 6.3 points, and
with a trained embedder gains 2.5. `facet_v1` — fusion drags a strong vector
arm down to a weak lexical one. LongMemEval, inside one benchmark: at 23 turns
a history fusion gains 3.4 points, at 491 turns it costs 6.0, the only change
being how much hay there is.

That rule is a **workaround for having no reranker.** Reciprocal-rank fusion
gives every arm equal rank votes, by design — it is scale-free, which is why it
was chosen — and the price is that it cannot notice an arm has gone bad. The
only defence left is choosing which arms to admit, which a deployment must do
before it knows how its corpus will behave.

A reranker scores candidates against the query directly and does not care which
arm proposed them. The registered claim is therefore not "this retrieves
better" but **"this makes fusion safe"**: see
`research/prereg/r2a-feature-reranker.md`.

## No model, and no weight

**No model.** A cross-encoder is a call per candidate, and
`research/results/p4-envelope.md` already has retrieval linear beyond a
thousand memories. The cheap version is tested first so that a win can be
attributed to reranking rather than to a bigger model.

**No tuned weight**, which is the part most likely to go wrong. Everything is
measured on one scale — the share of the query's **IDF mass** a candidate
accounts for — and a phrase match earns extra mass rather than entering through
a free coefficient. Proximity is a lexicographic tie-break, not a term in a
sum. There is nothing to fit, because a weight fitted on a dev split is how a
baseline quietly becomes a model, and this project has a standing rule against
tuned parameters in a baseline.

## What it cannot do

Reordering is not retrieval. If a weak arm has already pushed the answer out of
the pool, no reranker recovers it — which is prediction 1 of the registration,
recorded in advance.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

from .chains import tokens


@dataclass(frozen=True)
class Scored:
    memory_id: str
    coverage: float
    """Harmonic mean of two shares: how much of the query's IDF mass this
    candidate accounts for, and how much of the candidate is query material.

    Both halves are needed. Recall alone rewards a long candidate for
    mentioning many query words by chance; precision alone rewards a
    one-word candidate. The mean has no weight to fit."""
    proximity: float
    """1.0 when the matched query terms are adjacent, falling towards 0 as the
    window containing them grows. A tie-break only."""
    original_rank: int

    @property
    def key(self) -> tuple[float, float, int]:
        """Lexicographic: coverage, then proximity, then the fused order.

        Keeping the original rank as the final tie-break means a reranker with
        nothing to say leaves the pool exactly as it found it, so a null result
        is visibly null rather than a reshuffle.
        """
        return (-self.coverage, -self.proximity, self.original_rank)


def _bigrams(terms: Sequence[str]) -> set[tuple[str, str]]:
    return {(terms[i], terms[i + 1]) for i in range(len(terms) - 1)}


def score_candidate(
    query_terms: Sequence[str],
    query_bigrams: set[tuple[str, str]],
    idf: Mapping[str, float],
    content: str,
    rank: int,
    default_idf: float,
) -> Scored:
    """One candidate, on the IDF-mass scale.

    A query term the corpus has never used gets `default_idf` — the most any
    term is worth — because a word the store has never seen is the rarest thing
    it could be asked about. Without that, an unseen term contributes nothing
    and a candidate that happens to contain it is not rewarded.
    """
    doc_terms = tokens(content)
    doc_set = set(doc_terms)
    wanted = list(dict.fromkeys(query_terms))

    mass = sum(idf.get(t, default_idf) for t in wanted) or 1e-9
    matched = sum(idf.get(t, default_idf) for t in wanted if t in doc_set)

    # A phrase match earns the rarer of its two terms again. Extra mass on the
    # same scale rather than a separate feature with a weight: "this candidate
    # has the query's words *in order*" is worth about as much as having the
    # rarer of them a second time, and that is an argument rather than a fitted
    # coefficient.
    phrase_bonus = 0.0
    if query_bigrams:
        doc_bigrams = _bigrams(doc_terms)
        for left, right in query_bigrams & doc_bigrams:
            phrase_bonus += min(idf.get(left, default_idf),
                                idf.get(right, default_idf))

    recall = min(1.0, (matched + phrase_bonus) / mass)
    # Balanced against how much of the *candidate* is query material, which is
    # the fix for the only failure this mechanism has shown. Unnormalised
    # coverage took lexical from 0.768 to 0.679 on a sample of LongMemEval's
    # `s` split while *gaining* 0.174 on relevance_v2 -- because v2's memories
    # are uniform short facts and a chat turn is not, so a long rambling turn
    # matches more query words by chance and wins on recall alone.
    #
    # The harmonic mean of the two, which has no free parameter: a 100-term
    # turn containing all five query terms loses to a 6-term fact containing
    # the same five. Standard, and the standard reason.
    precision = (len([t for t in doc_terms if t in wanted]) / len(doc_terms)
                 if doc_terms else 0.0)
    coverage = (2 * recall * precision / (recall + precision)
                if (recall + precision) else 0.0)

    # Proximity: the tightest window in the candidate containing every matched
    # query term. 1.0 when they are adjacent.
    positions = [i for i, t in enumerate(doc_terms) if t in wanted]
    distinct = len({doc_terms[i] for i in positions})
    if distinct <= 1 or not positions:
        proximity = 1.0 if positions else 0.0
    else:
        best = len(doc_terms)
        seen: dict[str, int] = {}
        for index in positions:
            seen[doc_terms[index]] = index
            if len(seen) == distinct:
                best = min(best, index - min(seen.values()) + 1)
        proximity = distinct / best if best else 0.0

    return Scored(memory_id="", coverage=coverage, proximity=proximity,
                  original_rank=rank)


def rerank(
    query: str,
    candidates: Sequence[tuple[str, float]],
    contents: Mapping[str, str],
    idf: Mapping[str, float],
    mode: str = "tiebreak",
) -> list[tuple[str, float]]:
    """Reorder a fused pool. Returns (memory_id, score) best first.

    `mode="replace"` orders by coverage alone. **Measured to hurt**, and the
    reason is worth keeping: `LexicalIndex` already scores with
    *length-normalised* IDF, while coverage here is unnormalised, so replacing
    the retriever's score with a strictly weaker one promotes long rambling
    candidates that mention many query words over the short precise one that
    holds the answer. On a 60-instance sample of LongMemEval's `s` split it
    took lexical from 0.768 to 0.679.

    `mode="tiebreak"` keeps the retriever's score as primary and uses the two
    features it does **not** have — phrase order and proximity — to break
    ties. That is the only information this module adds, so it is the only
    thing it should decide. The default, because a reranker whose features are
    a subset of the retriever's cannot do better than reorder noise.

    Candidates whose content is unavailable keep their fused position:
    dropping a candidate is a retrieval decision and this is a reordering.
    """
    if not candidates:
        return []
    query_terms = tokens(query)
    if not query_terms:
        return list(candidates)
    query_bigrams = _bigrams(query_terms)
    default_idf = max(idf.values()) if idf else 1.0

    scored: list[Scored] = []
    for rank, (memory_id, _fused) in enumerate(candidates):
        content = contents.get(memory_id)
        if content is None:
            scored.append(Scored(memory_id=memory_id, coverage=-1.0,
                                 proximity=0.0, original_rank=rank))
            continue
        row = score_candidate(query_terms, query_bigrams, idf, content, rank,
                              default_idf)
        scored.append(Scored(memory_id=memory_id, coverage=row.coverage,
                             proximity=row.proximity, original_rank=rank))

    if mode == "replace":
        scored.sort(key=lambda s: s.key)
        return [(s.memory_id, s.coverage) for s in scored]
    if mode != "tiebreak":
        raise ValueError(f"unknown rerank mode {mode!r}")

    # Retriever score first, then the features it does not have. Ties on a
    # float score are rare, so this changes little by design -- which is the
    # honest shape of "add information, do not replace it", and makes a null
    # result visibly null.
    fused = {memory_id: value for memory_id, value in candidates}
    by_id = {s.memory_id: s for s in scored}
    order = sorted(
        (memory_id for memory_id, _ in candidates),
        key=lambda m: (
            -round(fused[m], 6),
            -by_id[m].coverage,
            -by_id[m].proximity,
            by_id[m].original_rank,
        ),
    )
    return [(memory_id, fused[memory_id]) for memory_id in order]
