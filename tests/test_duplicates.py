"""Copy recognition: the matching rule, and what it does to a store.

The rule is the one part of this that measurement chose against my first
design, so the measured comparison is pinned as a test rather than left in a
write-up: a Jaccard threshold catching real copies catches near-misses first,
and that would have put two memories about different sites under one source
root and called it deduplication.
"""

from __future__ import annotations

import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from memory_fabric import MemoryFabric, duplicates  # noqa: E402
from memory_fabric.model import LifecycleState  # noqa: E402

BULLETIN = ("Contractor bulletin CB-9: the inland quay is limited to 26 tonnes "
            "per square metre pending re-survey.")
COPY = BULLETIN + " (copy filed by the site office)"
DERIVED = "The inland quay limit is 26 tonnes per square metre per CB-9."
NEAR_MISS_A = "At the estuary site, swap the tug-8 signal cable every 180 days."
NEAR_MISS_B = "At the harbour site, swap the tug-8 signal cable every 180 days."


class TestTheRule(unittest.TestCase):
    def test_a_re_ingestion_with_an_added_note_is_a_copy(self):
        self.assertTrue(duplicates.is_copy(BULLETIN, COPY))
        self.assertTrue(duplicates.is_copy(COPY, BULLETIN))  # symmetric

    def test_a_near_miss_differing_by_one_facet_is_not_a_copy(self):
        self.assertFalse(duplicates.is_copy(NEAR_MISS_A, NEAR_MISS_B))

    def test_a_derived_restatement_is_not_a_copy(self):
        """It is handled by parent edges, and conflating the two would make a
        premise look like a duplicate of its conclusion."""
        self.assertFalse(duplicates.is_copy(BULLETIN, DERIVED))

    def test_jaccard_would_have_ordered_these_the_wrong_way_round(self):
        """The measurement that chose the rule, pinned.

        A copy *adds* a filing note, so Jaccard penalises it for growing; a
        near-miss differs by one token out of nine, so Jaccard barely notices.
        Any Jaccard threshold catching the copy catches the near-miss first.
        """
        t = duplicates.terms
        copy_j = duplicates.jaccard(t(BULLETIN), t(COPY))
        miss_j = duplicates.jaccard(t(NEAR_MISS_A), t(NEAR_MISS_B))
        self.assertLess(copy_j, miss_j)

        copy_c = duplicates.containment(t(BULLETIN), t(COPY))
        miss_c = duplicates.containment(t(NEAR_MISS_A), t(NEAR_MISS_B))
        self.assertEqual(copy_c, 1.0)
        self.assertLess(miss_c, 1.0)

    def test_a_short_memory_inside_a_long_one_is_not_a_copy(self):
        short = "The gate closes at 1800 daily."
        long = (short + " The weighbridge is calibrated every six months and "
                "the spill kit is mounted beside the fuel bund near bay nine.")
        self.assertTrue(duplicates.terms(short) <= duplicates.terms(long))
        self.assertFalse(duplicates.is_copy(short, long),
                         "the length guard must reject this")

    def test_very_short_content_is_excluded(self):
        self.assertFalse(duplicates.is_copy("gate closed", "gate closed now"))

    def test_find_copy_is_deterministic_under_ties(self):
        existing = {"zzz": BULLETIN, "aaa": BULLETIN}
        match = duplicates.find_copy(COPY, existing)
        self.assertIsNotNone(match)
        self.assertEqual(match.memory_id, "aaa")


class TestInAStore(unittest.TestCase):
    def _fabric(self, **kw):
        return MemoryFabric(":memory:", auto_activate=True,
                            encrypt_content=False, retrieval="lexical", **kw)

    def test_a_copy_shares_the_original_source_root(self):
        fabric = self._fabric()
        try:
            r1 = fabric.remember(agent_id="a", content=BULLETIN)
            r2 = fabric.remember(agent_id="b", content=COPY)
            self.assertEqual(fabric.state.copy_of.get(r2), r1)
            self.assertEqual(fabric.source_root(r2), fabric.source_root(r1))
        finally:
            fabric.close()

    def test_a_copy_is_not_a_parent_so_grouping_collapses_it(self):
        """The design constraint that made this a separate relation.

        `_group_by_root` spares a memory that is derivation-related to
        something already kept, because a premise and its conclusion are not
        copies. Recorded as a parent edge, a copy would be exempted from the
        very grouping that exists to collapse it.
        """
        fabric = self._fabric()
        try:
            r1 = fabric.remember(agent_id="a", content=BULLETIN)
            r2 = fabric.remember(agent_id="b", content=COPY)
            self.assertFalse(fabric._derivation_related(r1, r2))
            kept = fabric._group_by_root([(r1, 1.0), (r2, 0.9)], limit=10)
            self.assertEqual([k for k, _ in kept], [r1])
        finally:
            fabric.close()

    def test_re_ingesting_a_withdrawn_document_does_not_restore_it(self):
        fabric = self._fabric()
        try:
            r1 = fabric.remember(agent_id="a", content=BULLETIN)
            fabric.quarantine(r1, reason="wrong", actor="op", basis="contradicted")
            r2 = fabric.remember(agent_id="b", content=COPY)
            self.assertIs(fabric.state.memories[r2].lifecycle_state,
                          LifecycleState.CONTESTED)
        finally:
            fabric.close()

    def test_withdrawal_reaches_a_copy_written_earlier(self):
        """The symmetric half. The recorded edge runs newer -> older, so a
        copy stored *before* its original was once missed entirely."""
        fabric = self._fabric()
        try:
            r2 = fabric.remember(agent_id="b", content=COPY)
            r1 = fabric.remember(agent_id="a", content=BULLETIN)
            fabric.quarantine(r1, reason="wrong", actor="op", basis="contradicted")
            self.assertIs(fabric.state.memories[r2].lifecycle_state,
                          LifecycleState.CONTESTED)
        finally:
            fabric.close()

    def test_the_outcome_does_not_depend_on_ingestion_order(self):
        states = []
        for withdraw_first in (False, True):
            fabric = self._fabric()
            try:
                r1 = fabric.remember(agent_id="a", content=BULLETIN)
                if withdraw_first:
                    fabric.quarantine(r1, reason="wrong", actor="op",
                                      basis="contradicted")
                r2 = fabric.remember(agent_id="b", content=COPY)
                d = fabric.derive(agent_id="b", content=DERIVED, parents=[r2])
                if not withdraw_first:
                    fabric.quarantine(r1, reason="wrong", actor="op",
                                      basis="contradicted")
                states.append((
                    fabric.state.memories[r2].lifecycle_state,
                    fabric.state.memories[d].lifecycle_state,
                    fabric.source_root(d) == fabric.source_root(r1),
                ))
            finally:
                fabric.close()
        self.assertEqual(states[0], states[1])
        self.assertEqual(
            states[0],
            (LifecycleState.CONTESTED, LifecycleState.CONTESTED, True))

    def test_a_conclusion_derived_from_a_copy_resolves_to_the_original_root(self):
        """`source_root` resolves copy edges found by the lineage walk, not
        only the one it was handed."""
        fabric = self._fabric()
        try:
            r1 = fabric.remember(agent_id="a", content=BULLETIN)
            r2 = fabric.remember(agent_id="b", content=COPY)
            d = fabric.derive(agent_id="b", content=DERIVED, parents=[r2])
            self.assertEqual(fabric.source_root(d), fabric.source_root(r1))
        finally:
            fabric.close()

    def test_it_can_be_switched_off(self):
        fabric = self._fabric(recognise_copies=False)
        try:
            r1 = fabric.remember(agent_id="a", content=BULLETIN)
            r2 = fabric.remember(agent_id="b", content=COPY)
            self.assertEqual(fabric.state.copy_of, {})
            self.assertNotEqual(fabric.source_root(r2), fabric.source_root(r1))
        finally:
            fabric.close()

    def test_the_relation_survives_a_replay(self):
        """It is a projection of the log, so it must rebuild from it."""
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            path = str(pathlib.Path(tmp) / "store.db")
            first = MemoryFabric(path, auto_activate=True, encrypt_content=False)
            try:
                r1 = first.remember(agent_id="a", content=BULLETIN)
                r2 = first.remember(agent_id="b", content=COPY)
            finally:
                first.close()
            again = MemoryFabric(path, auto_activate=True, encrypt_content=False)
            try:
                self.assertEqual(again.state.copy_of.get(r2), r1)
                self.assertEqual(again.source_root(r2), again.source_root(r1))
            finally:
                again.close()


class TestIndependentKnowledgeSurvives(unittest.TestCase):
    """The other half of the requirement: correction must not destroy
    genuinely independent corroboration."""

    def test_an_independent_measurement_is_untouched(self):
        fabric = MemoryFabric(":memory:", auto_activate=True,
                              encrypt_content=False, retrieval="lexical")
        try:
            r1 = fabric.remember(agent_id="a", content=BULLETIN)
            trial = fabric.remember(
                agent_id="c",
                content="Load-cell trial LC-31 measured the inland quay at 31 "
                        "tonnes per square metre.")
            fabric.quarantine(r1, reason="wrong", actor="op", basis="contradicted")
            self.assertIs(fabric.state.memories[trial].lifecycle_state,
                          LifecycleState.ACTIVE)
            self.assertNotEqual(fabric.source_root(trial),
                                fabric.source_root(r1))
        finally:
            fabric.close()

    def test_a_conclusion_on_alternative_premises_survives_losing_one(self):
        fabric = MemoryFabric(":memory:", auto_activate=True,
                              encrypt_content=False)
        try:
            a = fabric.remember(
                agent_id="x",
                content="Survey alpha measured the quay at twenty six tonnes "
                        "per square metre.")
            b = fabric.remember(
                agent_id="y",
                content="Trial beta measured the quay at thirty one tonnes per "
                        "square metre on its own.")
            d = fabric.derive(
                agent_id="x",
                content="The quay rating is corroborated by two separate "
                        "measurements of it.",
                parents=[a, b],
                context={"justifications": {a: "alternative", b: "alternative"}},
            )
            fabric.quarantine(a, reason="wrong", actor="op", basis="contradicted")
            self.assertIs(fabric.state.memories[d].lifecycle_state,
                          LifecycleState.ACTIVE)
        finally:
            fabric.close()


if __name__ == "__main__":  # pragma: no cover
    unittest.main()


class TestTheIndexAgreesWithTheExhaustiveScan(unittest.TestCase):
    """The index narrows candidates; it must not change answers.

    It returns a superset and `is_copy` still decides, so a bug in it can only
    cost time -- but "can only cost time" is an argument, and this is the
    measurement. The exhaustive `find_copy` is kept precisely so the bounded
    path has something to be checked against.
    """

    def _corpus(self, n: int) -> dict[str, str]:
        return {
            f"m{i}": (f"unit-{i % 97} requires {1 + i % 9}.{i % 10} m of "
                      f"clearance at the site-{i % 31} depot")
            for i in range(n)
        }

    def test_the_two_paths_find_the_same_copy(self):
        store = self._corpus(400)
        index = duplicates.CopyIndex()
        for mid, content in store.items():
            index.add(mid, content)
        target = "unit-5 requires 4.4 m of clearance at the site-12 depot"
        store["orig"] = target
        index.add("orig", target)

        for suffix in ("", " (copy filed by the site office)", " [duplicate]"):
            probe = target + suffix
            with self.subTest(suffix=suffix):
                exhaustive = duplicates.find_copy(probe, store)
                indexed = index.find(probe)
                self.assertEqual(
                    (exhaustive and exhaustive.memory_id),
                    (indexed and indexed.memory_id))

    def test_the_two_paths_agree_that_a_near_miss_is_not_a_copy(self):
        store = self._corpus(200)
        index = duplicates.CopyIndex()
        for mid, content in store.items():
            index.add(mid, content)
        probe = "unit-5 requires 9.9 m of clearance at the site-12 depot"
        self.assertIsNone(duplicates.find_copy(probe, store))
        self.assertIsNone(index.find(probe))

    def test_it_finds_a_copy_in_both_directions(self):
        """The incoming side may be the longer or the shorter one.

        Indexing only the incoming content's own terms covers one direction and
        not the other, which is why each memory is also anchored under a few of
        its own terms.
        """
        short = BULLETIN
        long = COPY
        for first, second in ((short, long), (long, short)):
            with self.subTest(first=first[:20]):
                index = duplicates.CopyIndex()
                index.add("held", first)
                match = index.find(second)
                self.assertIsNotNone(match)
                self.assertEqual(match.memory_id, "held")

    def test_the_candidate_set_is_a_small_share_of_the_store(self):
        store = self._corpus(2000)
        index = duplicates.CopyIndex()
        for mid, content in store.items():
            index.add(mid, content)
        probe = ("unit-5 requires 4.4 m of clearance at the site-12 depot "
                 "(copy filed by the site office)")
        candidates = index.candidates(probe)
        self.assertLess(len(candidates), len(store) // 4,
                        f"{len(candidates)} of {len(store)} examined")
