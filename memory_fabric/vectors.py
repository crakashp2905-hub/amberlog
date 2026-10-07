"""Retrieval: embedder protocol plus a deterministic, dependency-free default.

The default embedder is hashed bag-of-words. It is deliberately not good: its
job is to make P1 reproducible and installable with zero dependencies while the
real model stays an open decision (ROADMAP.md, open item 8). Anything
implementing `Embedder` can replace it without touching the rest of the system.
"""

from __future__ import annotations

import hashlib
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
