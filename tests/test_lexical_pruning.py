"""Top-k pruning in LexicalIndex.search returns exactly what a full scan does."""

from __future__ import annotations

import heapq
import math
import random
import unittest

from amberlog.vectors import UBIQUITOUS_MIN_DOCS, UBIQUITOUS_SHARE, LexicalIndex


def brute(index: LexicalIndex, query: str, k: int, allowed=None, floor=0.0):
    q = set(index._tokens(query))
    w = index._idf()
    n = len(index._terms)
    cap = UBIQUITOUS_SHARE * n if n >= UBIQUITOUS_MIN_DOCS else float("inf")
    informative = {t for t in q if len(index._postings.get(t, ())) <= cap} or q
    out = []
    for key, terms in index._terms.items():
        if allowed is not None and key not in allowed or not terms:
            continue
        if not terms & informative:
            continue
        s = sum(w.get(t, 0.0) for t in terms & q) / math.sqrt(len(terms))
        if s > floor:
            out.append((key, s))
    return heapq.nsmallest(k, out, key=lambda p: (-p[1], p[0]))


class TestPruning(unittest.TestCase):
    def test_matches_a_full_scan_in_large_stores_too(self):
        from unittest import mock

        with mock.patch("amberlog.vectors.UBIQUITOUS_MIN_DOCS", 20), \
                mock.patch(f"{__name__}.UBIQUITOUS_MIN_DOCS", 20):
            self.test_matches_a_full_scan()

    def test_matches_a_full_scan(self):
        for seed in range(25):
            rng = random.Random(seed)
            vocab = [f"w{i}" for i in range(rng.randrange(5, 60))]
            common = vocab[:3]
            index = LexicalIndex()
            for d in range(rng.randrange(20, 400)):
                words = common + rng.sample(vocab, rng.randrange(1, min(12, len(vocab))))
                index.add(f"d{d:04d}", " ".join(words))
            for d in rng.sample(sorted(index._terms), 5):
                index.remove(d)
            keys = sorted(index._terms)
            for _ in range(20):
                query = " ".join(rng.sample(vocab, rng.randrange(1, 6)))
                k = rng.choice((1, 3, 5, 20))
                allowed = set(rng.sample(keys, len(keys) // 2)) if rng.random() < 0.3 else None
                self.assertEqual(index.search(query, k=k, restrict_to=allowed, min_relevance=0.0),
                                 brute(index, query, k, allowed), (seed, query, k))

    def test_common_words_do_not_scan_the_store(self):
        index = LexicalIndex()
        for i in range(5000):
            index.add(f"m{i}", f"pump relief pressure unit u{i} site s{i % 40}")
        hits = index.search("pump relief pressure u4321", k=20)
        self.assertEqual(hits, [("m4321", hits[0][1])])
        self.assertEqual(len(index.search("pump relief", k=5)), 5)


if __name__ == "__main__":
    unittest.main()
