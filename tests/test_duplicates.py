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
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from amberlog import Amberlog, duplicates  # noqa: E402
from amberlog.model import LifecycleState  # noqa: E402

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
        return Amberlog(":memory:", auto_activate=True,
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

    def test_truth_maintenance_agrees_that_the_copy_lost_its_support(self):
        """The engine contested the copy and `recompute` called it a justified
        root observation, so the integrity check (invariant 8) flagged a
        contested memory with surviving support. `faultsim`'s
        `cycle_terminates` found it: a federated round trip lands a copy back
        at the origin, and the origin's retraction contests it. Red in CI from
        the commit that added copy recognition onward."""
        for order in ("copy_first", "original_first"):
            with self.subTest(order):
                fabric = self._fabric()
                try:
                    if order == "copy_first":
                        r2 = fabric.remember(agent_id="b", content=COPY)
                        r1 = fabric.remember(agent_id="a", content=BULLETIN)
                    else:
                        r1 = fabric.remember(agent_id="a", content=BULLETIN)
                        r2 = fabric.remember(agent_id="b", content=COPY)
                    self.assertTrue(fabric.justifications.recompute(r2).still_justified)
                    fabric.quarantine(r1, reason="wrong", actor="op",
                                      basis="contradicted")
                    verdict = fabric.justifications.recompute(r2)
                    self.assertFalse(verdict.still_justified)
                    self.assertIn(r1, verdict.lost)
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
            first = Amberlog(path, auto_activate=True, encrypt_content=False)
            try:
                r1 = first.remember(agent_id="a", content=BULLETIN)
                r2 = first.remember(agent_id="b", content=COPY)
            finally:
                first.close()
            again = Amberlog(path, auto_activate=True, encrypt_content=False)
            try:
                self.assertEqual(again.state.copy_of.get(r2), r1)
                self.assertEqual(again.source_root(r2), again.source_root(r1))
            finally:
                again.close()


class TestIndependentKnowledgeSurvives(unittest.TestCase):
    """The other half of the requirement: correction must not destroy
    genuinely independent corroboration."""

    def test_an_independent_measurement_is_untouched(self):
        fabric = Amberlog(":memory:", auto_activate=True,
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
        fabric = Amberlog(":memory:", auto_activate=True,
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


class EncodingNoise(unittest.TestCase):
    """A withdrawn document pasted back with invisible or variant characters is
    still the same document. Before `canonical`, four of these came back as
    active, independent evidence."""

    DOC = "Contractor bulletin CB-9: torque the hub nuts on crane-5 to 450 Nm before every lift."
    VARIANTS = {
        "zero-width space": DOC.replace("torque", "tor\u200bque").replace("lift", "li\u200bft"),
        "ligature": DOC.replace("fi", "\ufb01"),
        "non-breaking hyphen": DOC.replace("CB-9", "CB\u20119").replace("crane-5", "crane\u20135"),
        "soft hyphen": DOC.replace("Contractor", "Con\u00adtractor"),
        "full-width digits": DOC.replace("450", "\uff14\uff15\uff10"),
    }

    def test_each_variant_is_recognised_as_the_document(self) -> None:
        from amberlog.duplicates import is_copy

        for name, variant in self.VARIANTS.items():
            with self.subTest(name):
                self.assertTrue(is_copy(self.DOC, variant))

    def test_a_reingested_variant_of_a_withdrawn_document_arrives_contested(self) -> None:
        from amberlog import LifecycleState, Amberlog

        for name, variant in self.VARIANTS.items():
            with self.subTest(name):
                fabric = Amberlog(auto_activate=True)
                try:
                    original = fabric.remember("a", self.DOC)
                    fabric.quarantine(original, reason="wrong torque", basis="contradicted")
                    copy = fabric.remember("b", variant)
                    self.assertIs(fabric.get(copy).lifecycle_state, LifecycleState.CONTESTED)
                    self.assertEqual(fabric.source_root(copy), fabric.source_root(original))
                finally:
                    fabric.close()

    def test_a_corrected_value_is_not_a_copy(self) -> None:
        """Normalisation must never merge distinct words: a correction stays new."""
        from amberlog.duplicates import is_copy

        self.assertFalse(is_copy(self.DOC, self.DOC.replace("450", "420")))


class TestIndexAgreesWithExhaustiveSearch(unittest.TestCase):
    """Randomised: the index finds exactly what the exhaustive scan finds, both directions.

    The anchors only matter when the incoming text is the *longer* side (a
    stored memory contained in it), so half the probes are a stored memory
    with words added, and half are a stored memory with words removed.
    """

    def test_random_corpora_both_directions(self) -> None:
        import random

        words = [f"w{i}" for i in range(60)] + ["purge", "time", "pressure", "valve", "site"]
        for seed in range(25):
            rng = random.Random(seed)
            store = {f"m{i}": " ".join(rng.sample(words, rng.randint(5, 9)))
                     for i in range(150)}
            index = duplicates.CopyIndex()
            for mid, content in store.items():
                index.add(mid, content)
            for _ in range(40):
                base = store[rng.choice(sorted(store))].split()
                if rng.random() < 0.5:
                    probe = base + rng.sample(words, 2)          # stored memory inside the probe
                else:
                    probe = rng.sample(base, max(5, len(base) - 1))  # probe inside a stored memory
                text = " ".join(probe)
                exhaustive = duplicates.find_copy(text, store)
                indexed = index.find(text)
                self.assertEqual(exhaustive and exhaustive.memory_id,
                                 indexed and indexed.memory_id, (seed, text))


class TestNearDuplicatesStayCheap(unittest.TestCase):
    """A store of near-identical notes must not make each write scan the whole store.

    Before the fix, every memory's third anchor tied on a common word, so one
    bucket held every memory, and the incoming text was re-tokenised for each
    candidate: ~29 ms a write at 5,000 notes, growing with the store.
    """

    @staticmethod
    def _note(i: int) -> str:
        return f"The purge time for P{i} is {20 + i % 41} s."

    def test_the_candidate_set_does_not_grow_with_the_store(self) -> None:
        index = duplicates.CopyIndex()
        for i in range(3000):
            index.add(f"m{i}", self._note(i))
        self.assertLess(len(index.candidates(self._note(99999))), 200)

    def test_copy_lookups_at_5000_are_at_most_3x_lookups_at_500(self) -> None:
        """Times copy recognition itself, so the storage backend does not enter into it.

        A whole-store write also grows with the log on PostgreSQL, for reasons
        unrelated to copy recognition; timing writes there failed this bound
        at 4.8x while the lookups it is about stayed flat.
        """
        import statistics
        import time

        def per_lookup(n: int) -> float:
            index = duplicates.CopyIndex()
            for i in range(n):
                index.add(f"m{i}", self._note(i))
            times = []
            for batch in range(5):
                t0 = time.perf_counter()
                for i in range(n + batch * 200, n + batch * 200 + 200):
                    index.find(self._note(i))
                times.append((time.perf_counter() - t0) / 200)
            return statistics.median(times)

        small, large = per_lookup(500), per_lookup(5000)
        self.assertLess(large, 3 * small, f"{large * 1e6:.1f} us vs {small * 1e6:.1f} us")


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
