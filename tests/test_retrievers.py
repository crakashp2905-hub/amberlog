"""Trained-retriever adapters, with fake backends (no model download)."""

from __future__ import annotations

import io
import json
import os
import tempfile
import unittest
from unittest import mock

from memory_fabric import MemoryFabric
from memory_fabric import retrievers
from memory_fabric.retrievers import (CrossEncoderReranker, HttpEmbedder, VectorCache,
                                      apply_reranker, best_available)


class WordEmbedder(retrievers._BatchEmbedder):
    """Deterministic: a vector per vocabulary word. Records batch sizes."""

    VOCAB = ("pump", "seal", "valve", "relief", "bar", "cable", "coastal", "sky")

    def __init__(self, cache_path=None):
        super().__init__("fake-words", cache_path, batch_size=4)
        self.batches: list[int] = []
        self.query_calls = 0

    def _documents(self, texts):
        self.batches.append(len(texts))
        return [[float(w in t.lower()) for w in self.VOCAB] for t in texts]

    def _queries(self, texts):
        self.query_calls += 1
        return self._documents(texts)


class KeywordReranker:
    pool = 10

    def __init__(self, word):
        self.word = word

    def score(self, query, texts):
        return [float(self.word in t) for t in texts]


class TestCaching(unittest.TestCase):
    def test_warm_batches_and_skips_cached(self):
        e = WordEmbedder()
        e.warm(["pump seal", "valve", "relief bar", "cable", "coastal", "pump seal"])
        self.assertEqual(e.batches, [4, 1])
        e.warm(["pump seal", "sky"])
        self.assertEqual(e.batches, [4, 1, 1])
        self.assertEqual(e.embed("valve"), e.embed("valve"))
        self.assertEqual(e.batches, [4, 1, 1])

    def test_queries_are_cached(self):
        e = WordEmbedder()
        e.embed_query("pump"), e.embed_query("pump")
        self.assertEqual(e.query_calls, 1)

    def test_disk_cache_survives_reopen(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "vectors.db")
            first = WordEmbedder(path)
            first.warm(["pump seal", "valve"])
            first.close()
            again = WordEmbedder(path)
            again.warm(["pump seal", "valve"])
            again.close()
            self.assertEqual(again.batches, [])
            if os.name == "posix":
                self.assertEqual(os.stat(path).st_mode & 0o777, 0o600)

    def test_cache_is_per_model(self):
        a, b = VectorCache("m1"), VectorCache("m2")
        a.put_many([("x", [1.0])])
        self.assertIsNone(b.get("x"))


class TestReranking(unittest.TestCase):
    def test_reorders_head_keeps_scores_and_tail(self):
        hits = [("a", 0.9), ("b", 0.8), ("c", 0.7)]
        texts = {"a": "no", "b": "yes", "c": "no"}
        out = apply_reranker(KeywordReranker("yes"), "q", hits, texts.__getitem__)
        self.assertEqual(out, [("b", 0.9), ("a", 0.8), ("c", 0.7)])
        small = KeywordReranker("yes")
        small.pool = 2
        out = apply_reranker(small, "q", hits + [("d", 0.1)], {**texts, "d": "yes"}.__getitem__)
        self.assertEqual([m for m, _ in out], ["b", "a", "c", "d"])

    def test_cross_encoder_wraps_a_backend(self):
        backend = mock.Mock()
        backend.rerank.return_value = iter([0.1, 2.0])
        r = CrossEncoderReranker(backend=backend)
        self.assertEqual(r.score("q", ["x", "y"]), [0.1, 2.0])
        self.assertEqual(r.score("q", []), [])


class TestInTheFabric(unittest.TestCase):
    def test_trained_embedder_and_reranker_in_retrieve(self):
        e = WordEmbedder()
        f = MemoryFabric(":memory:", auto_activate=True, retrieval="hybrid", embedder=e,
                         rerank=KeywordReranker("P-14"))
        self.addCleanup(f.close)
        for text in ("Pump P-15 relief valve is 9 bar.", "Pump P-14 relief valve is 12 bar.",
                     "Coastal cable is swapped."):
            f.remember("ag", text, scope="team")
        result = f.retrieve("ag", "pump relief valve bar", k=2)
        self.assertIn("P-14", result.exposed[0].content)
        self.assertGreaterEqual(e.query_calls, 1)

    def test_replay_warms_in_batches(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = os.path.join(tmp, "m.db")
            f = MemoryFabric(db, auto_activate=True)
            for i in range(9):
                f.remember("ag", f"pump {i} seal note {i}", scope="team")
            f.close()
            e = WordEmbedder()
            MemoryFabric(db, embedder=e, retrieval="hybrid").close()
            self.assertLess(len(e.batches), 9)


class TestHttpEmbedder(unittest.TestCase):
    def test_openai_shape_and_key_from_env(self):
        seen = {}

        def opener(request, timeout):
            seen["auth"] = request.get_header("Authorization")
            seen["body"] = json.loads(request.data)
            data = [{"index": i, "embedding": [float(i), 1.0]}
                    for i in range(len(seen["body"]["input"]))]
            return io.BytesIO(json.dumps({"data": data}).encode())

        with mock.patch.dict(os.environ, {"EMB_KEY": "k-test"}):
            e = HttpEmbedder("http://localhost:1/v1", "m", api_key_env="EMB_KEY",
                             opener=opener)
            self.assertEqual(e.embed("hi"), [0.0, 1.0])
        self.assertEqual(seen["auth"], "Bearer k-test")
        self.assertEqual(seen["body"], {"model": "m", "input": ["hi"]})
        self.assertFalse(any("k-test" in str(v) for v in vars(e).values()))

    def test_missing_key_fails_loudly(self):
        e = HttpEmbedder("http://x/v1", "m", api_key_env="NOPE_NOT_SET",
                         opener=lambda *a, **k: None)
        with mock.patch.dict(os.environ, {}, clear=True), self.assertRaises(RuntimeError):
            e.embed("x")


class TestBestAvailable(unittest.TestCase):
    def test_falls_back_to_lexical_without_fastembed(self):
        with mock.patch.object(retrievers, "fastembed_available", return_value=False):
            self.assertEqual(best_available(), {"retrieval": "lexical"})


if __name__ == "__main__":
    unittest.main()
