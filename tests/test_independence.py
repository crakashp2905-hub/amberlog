"""Source lineage and independent support (plan Task 6).

Acceptance, from the plan: copies are not counted as independent just because
their ids differ; similar independent reports are not automatically collapsed;
defaults change only with frozen evidence. The last is why the strict check is
opt-in and the near-copy signal is reported rather than acted on.
"""

from __future__ import annotations

import unittest

from memory_fabric import MemoryFabric
from memory_fabric import certificates as C
from memory_fabric.duplicates import containment, terms

ORIGINAL = "Crane 5 at the harbour lifts 12 tonnes at most, per the load chart."
VERBATIM = ORIGINAL
# Independent: another observer, other words, same fact.
INDEPENDENT = "Load test by the yard team: harbour crane 5 held 12 tonnes, no more."
# Near-copy: the original lightly edited -- uncertain, neither copy nor independent.
NEAR_COPY = "Crane 5 at the harbour lifts 12 tonnes at most, per the revised chart."


class Fixture(unittest.TestCase):
    def setUp(self) -> None:
        self.fabric = MemoryFabric(auto_activate=True, seed=0)
        self.addCleanup(self.fabric.close)

    def support(self, *contents: str, strict: bool = False):
        ids = [self.fabric.remember(f"ag{i}", text, scope="team") for i, text in enumerate(contents)]
        checks = [C.CHECK_STRICT_INDEPENDENCE if strict else C.CHECK_INDEPENDENT_SUPPORT]
        cert = self.fabric.certify("claim", ids, "ag9", required_checks=checks,
                                   min_independent_sources=2)
        return ids, self.fabric.verify_certificate(cert, "ag9")


class TestCopies(Fixture):
    def test_a_verbatim_reingestion_by_another_agent_is_one_source(self) -> None:
        ids, result = self.support(ORIGINAL, VERBATIM)
        self.assertNotEqual(ids[0], ids[1])
        self.assertEqual(result.independent_sources, 1)
        self.assertIn(C.INSUFFICIENT_INDEPENDENT_SUPPORT, result.reason_codes)

    def test_a_summary_is_not_independent_of_its_source(self) -> None:
        source = self.fabric.remember("ag1", ORIGINAL, scope="team")
        summary = self.fabric.derive("ag2", "Harbour crane 5 max 12 t.", parents=[source], scope="team")
        self.assertEqual(self.fabric.source_root(summary), self.fabric.source_root(source))


class TestIndependentReports(Fixture):
    def test_similar_independent_reports_are_not_collapsed(self) -> None:
        self.assertLess(containment(terms(ORIGINAL), terms(INDEPENDENT)),
                        C.NEAR_COPY_CONTAINMENT)
        _, result = self.support(ORIGINAL, INDEPENDENT)
        self.assertTrue(result.ok, result)
        self.assertEqual(result.independent_sources, 2)
        self.assertFalse(any(n.startswith("possible_copy") for n in result.notes))


class TestUncertainSimilarity(Fixture):
    """The band between "copy" and "independent" is reported, not decided."""

    def test_a_near_copy_is_reported_but_counted_by_default(self) -> None:
        self.assertGreaterEqual(containment(terms(ORIGINAL), terms(NEAR_COPY)),
                                C.NEAR_COPY_CONTAINMENT)
        _, result = self.support(ORIGINAL, NEAR_COPY)
        self.assertTrue(result.ok, result)
        self.assertEqual(result.independent_sources, 2)
        self.assertTrue(any(n.startswith("possible_copy") for n in result.notes))

    def test_the_strict_check_counts_a_near_copy_as_one(self) -> None:
        _, result = self.support(ORIGINAL, NEAR_COPY, strict=True)
        self.assertFalse(result.ok)
        self.assertEqual(result.checks[C.CHECK_STRICT_INDEPENDENCE], False)
        self.assertIn(C.INSUFFICIENT_INDEPENDENT_SUPPORT, result.reason_codes)

    def test_the_strict_check_still_counts_genuinely_independent_reports(self) -> None:
        _, result = self.support(ORIGINAL, INDEPENDENT, strict=True)
        self.assertTrue(result.ok, result)


if __name__ == "__main__":
    unittest.main()
