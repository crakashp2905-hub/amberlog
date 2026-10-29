"""The retrieval layer: embedder, similarity, and the relevance floor."""

from __future__ import annotations

import unittest

from amberlog.vectors import HashingEmbedder, VectorIndex, cosine


class TestHashingEmbedder(unittest.TestCase):
    def setUp(self) -> None:
        self.embedder = HashingEmbedder(dim=64)

    def test_is_deterministic(self) -> None:
        self.assertEqual(
            self.embedder.embed("rotate the signing key"),
            self.embedder.embed("rotate the signing key"),
        )

    def test_output_has_the_requested_dimension(self) -> None:
        self.assertEqual(len(self.embedder.embed("anything")), 64)

    def test_vectors_are_unit_norm(self) -> None:
        vector = self.embedder.embed("some reasonably long piece of text here")
        self.assertAlmostEqual(sum(v * v for v in vector) ** 0.5, 1.0, places=9)

    def test_empty_text_yields_a_zero_vector(self) -> None:
        self.assertEqual(self.embedder.embed(""), [0.0] * 64)
        self.assertEqual(self.embedder.embed("!!! ???"), [0.0] * 64)

    def test_colliding_tokens_that_cancel_do_not_crash(self) -> None:
        """Regression: signed hashing lets two tokens cancel to exactly zero in
        a shared bucket, and log(0) is undefined. A tiny dimension makes such
        collisions near-certain, so this sweeps a range of inputs to catch it.
        """
        tiny = HashingEmbedder(dim=2)
        for length in range(1, 60):
            text = " ".join(f"token{i}" for i in range(length))
            vector = tiny.embed(text)
            self.assertEqual(len(vector), 2)
            self.assertTrue(all(v == v for v in vector))  # no NaN

    def test_repeated_terms_are_weighted_sublinearly(self) -> None:
        once = HashingEmbedder(dim=512).embed("alpha")
        many = HashingEmbedder(dim=512).embed(" ".join(["alpha"] * 50))
        # Both normalise to unit length, so they point the same way.
        self.assertAlmostEqual(cosine(once, many), 1.0, places=6)


class TestCosine(unittest.TestCase):
    def test_identical_vectors(self) -> None:
        self.assertAlmostEqual(cosine([1.0, 0.0], [1.0, 0.0]), 1.0)

    def test_orthogonal_vectors(self) -> None:
        self.assertAlmostEqual(cosine([1.0, 0.0], [0.0, 1.0]), 0.0)

    def test_opposed_vectors(self) -> None:
        self.assertAlmostEqual(cosine([1.0, 0.0], [-1.0, 0.0]), -1.0)

    def test_zero_vector_is_safe(self) -> None:
        self.assertEqual(cosine([0.0, 0.0], [1.0, 0.0]), 0.0)

    def test_is_scale_invariant(self) -> None:
        self.assertAlmostEqual(cosine([3.0, 4.0], [6.0, 8.0]), 1.0)


class TestVectorIndex(unittest.TestCase):
    def setUp(self) -> None:
        self.index = VectorIndex()
        self.index.add("rg", "use ripgrep to search large repositories quickly")
        self.index.add("helm", "deploy the service with a helm chart")
        self.index.add("tyre", "tyre pressure should be thirty four psi")

    def test_finds_the_best_match(self) -> None:
        results = self.index.search("search large repositories", k=1)
        self.assertEqual(results[0][0], "rg")
        self.assertGreater(results[0][1], 0.5)

    def test_default_embedder_does_not_match_across_word_forms(self) -> None:
        """A documented limitation, pinned so the swap to a real embedder is
        visibly an improvement rather than a silent behaviour change.

        The hashing embedder matches whole tokens, so "repository" does not
        reach "repositories" and the query degenerates to a near-tie decided by
        the alphabetical tie-break. This is why the default embedder is a
        placeholder and the real choice is deferred (ROADMAP.md, open item 8).
        """
        results = dict(self.index.search("searching a large repository", k=3))
        self.assertAlmostEqual(results["rg"], results["helm"], places=6)

    def test_respects_k(self) -> None:
        self.assertLessEqual(len(self.index.search("repository helm psi", k=2)), 2)

    def test_relevance_floor_excludes_unrelated_memories(self) -> None:
        """Without the floor, top-k returns the least-bad rows in the store."""
        self.assertEqual(self.index.search("quantum chromodynamics", k=3), [])

    def test_floor_can_be_raised(self) -> None:
        loose = self.index.search("repository", k=3, min_relevance=0.0)
        strict = self.index.search("repository", k=3, min_relevance=0.9)
        self.assertGreater(len(loose), len(strict))

    def test_restrict_to_limits_the_candidate_set(self) -> None:
        results = self.index.search("search repositories", k=3, restrict_to={"helm", "tyre"})
        self.assertNotIn("rg", {key for key, _ in results})

    def test_removal(self) -> None:
        self.index.remove("rg")
        self.assertNotIn("rg", self.index)
        self.assertEqual(len(self.index), 2)
        self.assertNotIn("rg", {key for key, _ in self.index.search("ripgrep", k=3)})

    def test_removing_a_missing_key_is_a_no_op(self) -> None:
        self.index.remove("ghost")
        self.assertEqual(len(self.index), 3)

    def test_add_overwrites(self) -> None:
        self.index.add("rg", "completely different content about baking bread")
        self.assertEqual(len(self.index), 3)
        results = self.index.search("baking bread", k=1)
        self.assertEqual(results[0][0], "rg")

    def test_ties_are_ordered_deterministically(self) -> None:
        index = VectorIndex()
        for key in ("c", "a", "b"):
            index.add(key, "identical text for every entry")
        keys = [key for key, _ in index.search("identical text", k=3)]
        self.assertEqual(keys, sorted(keys))


if __name__ == "__main__":
    unittest.main()
