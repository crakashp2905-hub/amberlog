"""The inverted index returns exactly what scoring every document returned, and change tracking misses nothing."""

from __future__ import annotations

import math
import random
import unittest

from memory_fabric import MemoryFabric
from memory_fabric.vectors import LexicalIndex

WORDS = "pump valve boiler seal bar pressure leak rotterdam porto night shift handover p1 p2 p3 v7".split()


def full_scan(index: LexicalIndex, query: str, k: int, allowed: set[str] | None) -> list:
    terms = set(index._tokens(query))
    weights = index._idf()
    out = []
    for key, doc in index._terms.items():
        if (allowed is not None and key not in allowed) or not doc:
            continue
        score = sum(weights.get(t, 0.0) for t in doc & terms) / math.sqrt(len(doc))
        if score > 0.0:
            out.append((key, score))
    out.sort(key=lambda p: (-p[1], p[0]))
    return out[:k]


class Equivalence(unittest.TestCase):
    def test_random_corpora_adds_removes_and_restrictions(self) -> None:
        rng = random.Random(5)
        for trial in range(40):
            index = LexicalIndex()
            keys = []
            for n in range(rng.randint(5, 60)):
                key = f"m{n}"
                index.add(key, " ".join(rng.choices(WORDS, k=rng.randint(1, 8))))
                keys.append(key)
            for key in rng.sample(keys, len(keys) // 4):
                index.remove(key)
            for key in rng.sample(keys, len(keys) // 4):
                index.add(key, " ".join(rng.choices(WORDS, k=4)))  # re-add / overwrite
            for _ in range(10):
                q = " ".join(rng.choices(WORDS, k=rng.randint(1, 4)))
                allowed = set(rng.sample(keys, len(keys) // 2)) if rng.random() < 0.5 else None
                self.assertEqual(index.search(q, k=10, restrict_to=allowed, min_relevance=0.0),
                                 full_scan(index, q, 10, allowed), (trial, q))


class ChangeTracking(unittest.TestCase):
    def test_every_transition_reaches_the_index(self) -> None:
        f = MemoryFabric(":memory:", auto_activate=True)
        self.addCleanup(f.close)
        mid = f.remember("a", "Valve V7 opens at 3 bar.", scope="team")
        f.revise(mid, "Valve V7 opens at 4 bar.", agent_id="a", reason="r")
        self.assertIn(mid, {m.id for m in f.retrieve("a", "valve v7 4 bar").exposed})
        f.forget(mid, reason="old", actor="lead")
        self.assertNotIn(mid, {m.id for m in f.retrieve("a", "valve v7").exposed})
        f.validate(mid, actor="lead")
        self.assertIn(mid, {m.id for m in f.retrieve("a", "valve v7").exposed})


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
