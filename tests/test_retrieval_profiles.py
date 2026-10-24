"""Retrieval profiles: per-workload settings chosen per call."""

from __future__ import annotations

import inspect
import unittest
from unittest import mock

from memory_fabric import MemoryFabric
from memory_fabric._fabric import retrieval as R
from memory_fabric.retrieval_profiles import PROFILES, RetrievalProfile, resolve


class Profiles(unittest.TestCase):
    def setUp(self) -> None:
        self.f = MemoryFabric(auto_activate=True)
        self.addCleanup(self.f.close)
        for i in range(30):
            self.f.remember("ag", f"Pump P-{10 + i}: the relief pressure is {10 + i} bar.")

    def test_defaults_table_matches_the_signature(self) -> None:
        sig = inspect.signature(R.RetrievalMixin.retrieve).parameters
        for key, value in R._RETRIEVE_DEFAULTS.items():
            self.assertEqual(sig[key].default, value, key)

    def test_a_profile_sets_k(self) -> None:
        self.assertEqual(len(self.f.retrieve("ag", "pump relief pressure", profile="conversational")), 10)
        self.assertEqual(len(self.f.retrieve("ag", "pump relief pressure", profile="precise")), 5)

    def test_an_explicit_argument_wins(self) -> None:
        self.assertEqual(len(self.f.retrieve("ag", "pump relief pressure", profile="audit", k=3)), 3)

    def test_method_is_per_call(self) -> None:
        seen = []
        real = R.RetrievalMixin._search

        def spy(self, query, k, eligible, min_relevance, method=None):
            seen.append(method)
            return real(self, query, k, eligible, min_relevance, method=method)

        with mock.patch.object(R.RetrievalMixin, "_search", spy):
            self.f.retrieve("ag", "pump", profile="semantic")
            self.f.retrieve("ag", "pump", method="vector")
            self.f.retrieve("ag", "pump")
        self.assertEqual(seen, ["hybrid", "vector", None])
        self.assertEqual(self.f.retrieval_mode, "lexical", "the store default is unchanged")

    def test_every_method_finds_the_same_memories_exist(self) -> None:
        ids = {m: {x.id for x in self.f.retrieve("ag", "pump relief pressure", k=30, method=m)}
               for m in ("lexical", "hybrid", "vector")}
        self.assertTrue(all(ids.values()))

    def test_unknown_profile_and_method_are_refused(self) -> None:
        with self.assertRaises(ValueError):
            self.f.retrieve("ag", "pump", profile="nope")
        with self.assertRaises(ValueError):
            self.f.retrieve("ag", "pump", method="nope")
        with self.assertRaises(ValueError):
            RetrievalProfile("x", "bogus")

    def test_custom_profile_per_store(self) -> None:
        self.f.retrieval_profiles = {"tiny": RetrievalProfile("tiny", "lexical", {"k": 2})}
        self.assertEqual(len(self.f.retrieve("ag", "pump relief pressure", profile="tiny")), 2)

    def test_every_built_in_profile_cites_its_evidence(self) -> None:
        for p in PROFILES.values():
            self.assertTrue(p.evidence, p.name)
        self.assertIs(resolve("precise"), PROFILES["precise"])


if __name__ == "__main__":
    unittest.main()
