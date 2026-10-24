"""Retrieval: embedder protocol plus a deterministic, dependency-free default.

The default embedder is hashed bag-of-words. It is deliberately not good: its
job is to make P1 reproducible and installable with zero dependencies while the
real model stays an open decision (ROADMAP.md, open item 8). Anything
implementing `Embedder` can replace it without touching the rest of the system.
"""

from __future__ import annotations

__stability__ = "stable"

import hashlib
import heapq
import math
import re
from typing import Iterable, Protocol, Sequence

_TOKEN = re.compile(r"[a-z0-9]+")

MIN_RELEVANCE = 1e-6
"""Default relevance floor: strictly positive cosine similarity.

Chosen rather than tuned. It excludes only the cases that carry no information
at all (no overlapping signal, or an actively opposed one) and leaves any real
threshold choice to the caller, since the right value depends on the embedder.
"""


_STOPWORDS = frozenset(
    "the a an is are was were be been it its of for to in on at and or not "
    "do does did should what which how why when who with from this that "
    "still can could we i me my our us".split()
)


class LexicalIndex:
    """IDF-weighted token overlap. The arm the product was missing.

    `relevance_v1` measured the shipping vector path as the **weakest
    non-broken arm** — 0.728 on dev and 0.485 on the frozen test split —
    losing to exactly this by 5 and 32 points
    ([result](../research/results/relevance-v1-ceiling.md)). The cause is not
    the retrieval design: it is that `HashingEmbedder` is a hashed bag of words
    rather than a trained model, so near-synonyms do not help it and shared
    rare terms do not help it enough.

    Deliberately not BM25. Full BM25 needs a tuned `k1` and `b`, and tuning
    those on the dev split before a ranker milestone exists is how a baseline
    becomes a fitted model. Length-normalised IDF overlap has no free
    parameters.
    """

    def __init__(self) -> None:
        self._terms: dict[str, frozenset[str]] = {}
        # term -> keys containing it. A search scores only documents sharing a
        # query term; every other document scores 0, which no non-negative
        # floor admits. Scanning every document instead made a query cost
        # grow linearly with the store: 39 ms p50 at 20,000 memories
        # (research/results/product-bench.md).
        self._postings: dict[str, set[str]] = {}
        # IDF depends on the corpus and not on the query, so it is computed
        # once and invalidated on write. It used to be recomputed inside every
        # `search` — a full scan of every document and all its terms, per
        # query, O(corpus x queries).
        #
        # Measured: 27 ms/query uncached against 9.6 ms cached over 5,000
        # documents, so **3x**, or 8 seconds against 3 for SciFact's 300
        # queries. Worth having and *not* what made the first external run
        # slow — I guessed that it was and the measurement said otherwise. The
        # cost is the dense vector scan; see `VectorIndex.search`.
        self._idf_cache: dict[str, float] | None = None

    def add(self, key: str, text: str) -> str:
        if key in self._terms:
            self.remove(key)
        terms = frozenset(self._tokens(text))
        self._terms[key] = terms
        for term in terms:
            self._postings.setdefault(term, set()).add(key)
        self._idf_cache = None
        return key

    def remove(self, key: str) -> None:
        terms = self._terms.pop(key, None)
        if terms is not None:
            for term in terms:
                keys = self._postings.get(term)
                if keys is not None:
                    keys.discard(key)
                    if not keys:
                        del self._postings[term]
            self._idf_cache = None

    def __len__(self) -> int:
        return len(self._terms)

    @staticmethod
    def _tokens(text: str) -> list[str]:
        return [t for t in _TOKEN.findall(text.lower()) if t not in _STOPWORDS]

    def _idf(self) -> dict[str, float]:
        if self._idf_cache is not None:
            return self._idf_cache
        total = len(self._terms)
        counts: dict[str, int] = {}
        for terms in self._terms.values():
            for term in terms:
                counts[term] = counts.get(term, 0) + 1
        self._idf_cache = {
            term: math.log((total + 1) / (count + 0.5))
            for term, count in counts.items()
        }
        return self._idf_cache

    def search(
        self,
        query: str,
        k: int = 5,
        restrict_to: Iterable[str] | None = None,
        min_relevance: float = MIN_RELEVANCE,
    ) -> list[tuple[str, float]]:
        query_terms = set(self._tokens(query))
        if not query_terms:
            return []
        weights = self._idf()
        allowed = set(restrict_to) if restrict_to is not None else None
        scored: list[tuple[str, float]] = []
        if min_relevance >= 0:
            candidates: set[str] = set()
            for term in query_terms:
                candidates |= self._postings.get(term, set())
            if allowed is not None:
                candidates &= allowed
            pool: Iterable[str] = candidates
        else:  # a negative floor admits documents sharing nothing: score them all
            pool = self._terms if allowed is None else (k_ for k_ in self._terms if k_ in allowed)
        for key in pool:
            terms = self._terms[key]
            if not terms:
                continue
            overlap = sum(weights.get(t, 0.0) for t in terms & query_terms)
            # Length-normalised, or a long memory wins by containing more
            # words rather than better ones.
            score = overlap / math.sqrt(len(terms))
            if score > min_relevance:
                scored.append((key, score))
        # Top k without sorting every candidate; same order as a full sort.
        return heapq.nsmallest(k, scored, key=lambda pair: (-pair[1], pair[0]))


def fuse(
    *ranked: Sequence[tuple[str, float]], k: int = 5, constant: int = 60
) -> list[tuple[str, float]]:
    """Reciprocal-rank fusion across retrieval arms.

    RRF rather than a weighted sum of scores, because cosine similarity and
    IDF overlap are on incomparable scales and a weight between them would be
    a tuned parameter — on the dev split, before any ranker milestone exists.
    RRF needs only the ranks.

    `constant` is the standard 60 from the original RRF paper, left alone for
    the same reason.

    The returned score is a fusion rank, **not** a relevance value, and is not
    comparable to a cosine. Callers that need a relevance number should take it
    from the arm they care about.
    """
    fused: dict[str, float] = {}
    for results in ranked:
        for position, (key, _score) in enumerate(results):
            fused[key] = fused.get(key, 0.0) + 1.0 / (constant + position + 1)
    ordered = sorted(fused.items(), key=lambda pair: (-pair[1], pair[0]))
    return ordered[:k]


class Embedder(Protocol):
    dim: int

    def embed(self, text: str) -> list[float]: ...


class HashingEmbedder:
    """Deterministic hashed bag-of-words with sublinear term weighting."""

    def __init__(self, dim: int = 256) -> None:
        self.dim = dim

    def embed(self, text: str) -> list[float]:
        counts: dict[int, float] = {}
        for token in _TOKEN.findall(text.lower()):
            digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
            bucket = int.from_bytes(digest, "big") % self.dim
            # Signed hashing reduces the bias from collisions.
            sign = 1.0 if digest[0] & 1 else -1.0
            counts[bucket] = counts.get(bucket, 0.0) + sign
        vector = [0.0] * self.dim
        for bucket, count in counts.items():
            # Signed hashing means two colliding tokens can cancel exactly.
            # A zero bucket carries no signal, and log(0) is undefined.
            if count == 0.0:
                continue
            vector[bucket] = math.copysign(1.0 + math.log(abs(count)), count)
        norm = math.sqrt(sum(v * v for v in vector))
        if norm > 0.0:
            vector = [v / norm for v in vector]
        return vector


def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    """Cosine similarity. Inputs from `HashingEmbedder` are already unit-norm,
    but normalising here keeps the function correct for any embedder."""
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


SPARSE_QUERY_FRACTION = 0.25


class VectorIndex:
    """Flat in-memory index. Exact search, linear scan.

    Fine to thousands of memories, which is the P1 target. The upgrade path
    (pgvector, Qdrant) is behind this same interface (ARCHITECTURE.md section 4).

    **The dimension matters more than the count, and the measurement that
    retired distribution was taken at the wrong dimension.** P9 declined a
    distributed backend on measurement — 4.39 ms per retrieval at 2,000
    memories — with the 256-dim hashing embedder and its sparse-query shortcut.
    A real 768-dim embedder produces *dense* queries, so that shortcut never
    fires and every query is a full dense dot product:

    | | 2,000 docs | 5,183 docs |
    |---|---|---|
    | hashed, 256-dim, sparse query | ~4 ms | — |
    | trained, 768-dim, dense query | **210 ms** | **544 ms** |

    That is ~50x at the same corpus size, and SciFact is the reason to want the
    trained embedder. So P9's conclusion holds for the embedder it was measured
    with and **does not transfer** to the one the evidence now recommends.

    **Re-measured 2026-10-13, and the dominant cost is not the scan.** On
    LongMemEval a trained-embedder retrieval costs **393 ms** on a corpus of
    **23 documents** -- one model call to embed the *query*, which is
    independent of corpus size and swamps the scan at any size this project
    has measured. Against the **4.39 ms** P9 declined distribution on, that is
    89x before a single document is compared
    (`research/results/longmemeval.md` section 5a).

    And the same run removed the premise: on short conversational turns the
    trained embedder is the **weaker** arm, 0.811 against the hashed 0.820,
    where on SciFact's abstracts it was 0.701 against 0.315. The embedder's
    value is a property of the corpus, so "pay 393 ms for the trained one" is
    not a general trade either. Principle 9 still applies -- nothing here says
    distribution is needed, only that P9's number was taken at the wrong
    dimension and is now measured at the right one.

    Two optimisations, because a linear scan in pure Python is where all the
    time goes: vectors are normalised once on insert rather than on every
    comparison, and a sparse query is scored only over the dimensions it
    actually occupies. A short query against the hashing embedder touches a
    handful of dimensions instead of every one, which is the difference between
    a scan costing `n × dim` and `n × terms`.
    """

    def __init__(self, embedder: Embedder | None = None) -> None:
        self.embedder = embedder or HashingEmbedder()
        self._vectors: dict[str, list[float]] = {}

    def add(self, key: str, text: str) -> str:
        vector = self.embedder.embed(text)
        norm = math.sqrt(sum(v * v for v in vector))
        if norm > 0.0:
            vector = [v / norm for v in vector]
        self._vectors[key] = vector
        return key

    def remove(self, key: str) -> None:
        self._vectors.pop(key, None)

    def __contains__(self, key: str) -> bool:
        return key in self._vectors

    def __len__(self) -> int:
        return len(self._vectors)

    def search(
        self,
        query: str,
        k: int = 5,
        restrict_to: Iterable[str] | None = None,
        min_relevance: float = MIN_RELEVANCE,
    ) -> list[tuple[str, float]]:
        """Top-k by cosine similarity, above a relevance floor.

        Returns relevance only. Ranking by *value* happens above this layer,
        because conflating the two is the mistake the whole project is about
        (AGENTS.md principle 1).

        The floor matters more than it looks. Without it, top-k returns the
        k least-bad matches however bad they are, so a query with nothing
        relevant to find still fills the agent's context with noise, and a store
        whose good memories have been retracted starts serving its irrelevant
        ones. A score at or below zero means no shared signal at all.
        """
        query_vector = self.embedder.embed(query)
        query_norm = math.sqrt(sum(v * v for v in query_vector))
        if query_norm == 0.0:
            return []
        query_vector = [v / query_norm for v in query_vector]

        # Stored vectors are already unit-norm, so cosine is a plain dot product.
        nonzero = [(i, v) for i, v in enumerate(query_vector) if v != 0.0]
        sparse = len(nonzero) <= SPARSE_QUERY_FRACTION * len(query_vector)

        allowed = set(restrict_to) if restrict_to is not None else None
        scored: list[tuple[str, float]] = []
        for key, vector in self._vectors.items():
            if allowed is not None and key not in allowed:
                continue
            if sparse:
                score = 0.0
                for index, weight in nonzero:
                    other = vector[index]
                    if other:
                        score += weight * other
            else:
                score = sum(a * b for a, b in zip(query_vector, vector))
            if score >= min_relevance:
                scored.append((key, score))
        # Sort by score, then key, so ties are broken deterministically.
        scored.sort(key=lambda pair: (-pair[1], pair[0]))
        return scored[:k]
