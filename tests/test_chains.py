"""The chain search, on plain strings.

Every test here is a bug the search shipped with during development, pinned so
it cannot come back. The search is pure — it takes candidate ids, their terms
and the query terms — so the connector case can be stated in six memories
instead of five hundred, which is how three of these four defects were found.
"""

from __future__ import annotations

import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from memory_fabric import chains  # noqa: E402
from memory_fabric.relevance import ReasonCode  # noqa: E402

# bay 7 -> tug-3 -> heavy axle set -> pressure. The query names the bay, the
# site and the season; the middle memory names none of them.
CHAIN = {
    "h1": "bay 7 coastal site assigned tug-3",
    "h2": "tug-3 re-fitted heavy axle set march",
    "h3": "vehicles heavy axle set run 4.2 bar winter",
    "d1": "bay 8 coastal site assigned crane-2",
    "d2": "vehicles light axle set run 3.0 bar winter",
    "d3": "coastal site canteen reopens 0600 winter",
}
NEED = ["bay", "7", "coastal", "site", "run", "winter"]


def terms_of(corpus: dict[str, str]) -> dict[str, list[str]]:
    return {k: chains.tokens(v) for k, v in corpus.items()}


class TestTheConnectorIsFound(unittest.TestCase):
    def test_a_three_hop_chain_includes_the_memory_with_no_query_term(self):
        chain = chains.search(list(CHAIN), terms_of(CHAIN), NEED)
        self.assertTrue(chain.complete)
        self.assertIn("h2", chain.memory_ids)
        self.assertEqual(set(chain.memory_ids), {"h1", "h2", "h3"})

    def test_the_connector_is_labelled_dependency_required(self):
        """The reason code that had no producer anywhere before this."""
        chain = chains.search(list(CHAIN), terms_of(CHAIN), NEED)
        step = next(s for s in chain.steps if s.memory_id == "h2")
        self.assertIs(step.reason, ReasonCode.DEPENDENCY_REQUIRED)
        self.assertEqual(step.covers, ())
        self.assertTrue(step.bridges)

    def test_every_step_of_a_minimal_chain_is_necessary(self):
        chain = chains.search(list(CHAIN), terms_of(CHAIN), NEED)
        self.assertEqual(set(chain.necessary_ids), {"h1", "h2", "h3"})

    def test_why_names_the_role_and_the_link(self):
        chain = chains.search(list(CHAIN), terms_of(CHAIN), NEED)
        why = chain.why("h2")
        self.assertIn("necessary", why)
        self.assertIn("supplies no query term directly", why)
        self.assertIn("tug-3", why)


class TestCoverageAloneIsNotEnough(unittest.TestCase):
    """The first defect: a covering pair that shares nothing.

    h1 and h3 between them mention every query term and have nothing to do with
    each other. Scored on coverage alone the search returned exactly those two
    and skipped the memory that joins them.
    """

    def test_a_covering_but_unrelated_pair_is_not_a_complete_chain(self):
        pair = {k: CHAIN[k] for k in ("h1", "h3")}
        chain = chains.search(list(pair), terms_of(pair), NEED)
        self.assertFalse(chain.connected)
        self.assertFalse(chain.complete)
        self.assertEqual(chain.missing, ())  # covered, and still not a chain

    def test_connectedness_is_required_not_merely_preferred(self):
        with_bridge = {k: CHAIN[k] for k in ("h1", "h3", "h2")}
        chain = chains.search(list(with_bridge), terms_of(with_bridge), NEED)
        self.assertTrue(chain.complete)
        self.assertEqual(len(chain.steps), 3)


class TestBridgesMustBeDiscriminating(unittest.TestCase):
    """The second defect: joining `tug-3` to `3.0 bar` through the token "3".

    `LexicalIndex` tokenises on `[a-z0-9]+`, so "tug-3" became "tug" and "3",
    "3.0" also became "3", and the search produced a confident wrong answer in
    two steps.
    """

    def test_identifiers_survive_tokenisation(self):
        self.assertIn("tug-3", chains.tokens("assigned to tug-3."))
        self.assertNotIn("3", chains.tokens("assigned to tug-3."))

    def test_a_bare_number_is_not_a_link(self):
        left, right = frozenset({"tug-3", "3"}), frozenset({"3", "bar"})
        self.assertEqual(
            chains._bridge_terms(left, right, frozenset()), set())

    def test_the_wrong_axle_rule_is_not_chosen_over_the_right_one(self):
        chain = chains.search(list(CHAIN), terms_of(CHAIN), NEED)
        self.assertNotIn("d2", chain.memory_ids)


class TestBridgesAreReachable(unittest.TestCase):
    """The third defect, and the one that cost the most.

    A bridge was admissible only while the set was *disconnected*. A one-memory
    state is trivially connected, so the first hop could never reach its own
    connector; and once two memories covered everything, a rule gated on
    incompleteness could not join them either. Both conditions are needed.
    """

    def test_a_connector_is_reachable_from_a_single_seed(self):
        # Only h1 can seed: h3 is removed, so coverage must come through the
        # connector's far side.
        corpus = {k: CHAIN[k] for k in ("h1", "h2", "h3")}
        chain = chains.search(["h1", "h2", "h3"], terms_of(corpus), NEED,
                              beam=2)
        self.assertTrue(chain.complete)
        self.assertIn("h2", chain.memory_ids)

    def test_a_connector_is_reachable_once_coverage_is_already_complete(self):
        corpus = {k: CHAIN[k] for k in ("h1", "h3", "h2")}
        chain = chains.search(["h1", "h3", "h2"], terms_of(corpus), NEED)
        self.assertTrue(chain.connected)
        self.assertIn("h2", chain.memory_ids)


class TestContradictionsAreSurfaced(unittest.TestCase):
    """A search for *a* sufficient set returns one side of a disagreement.

    Measured: `conflicting` fell from 0.667 to 0.000 when the chain arm was
    first scored, because one memory covered every query term on its own.
    """

    def test_a_rival_answer_with_equal_coverage_is_added(self):
        corpus = {
            "a1": "harbour site electrical-isolation permit needed forklift-14 work log",
            "a2": "harbour site hot-work permit needed forklift-14 work sheet",
            "n1": "inland site hot-work permit needed forklift-14 work",
        }
        need = ["permit", "forklift-14", "harbour", "site", "work"]
        chain = chains.search(list(corpus), terms_of(corpus), need)
        self.assertEqual({"a1", "a2"}, set(chain.memory_ids))

    def test_a_near_miss_covering_less_is_not_added(self):
        corpus = {
            "a1": "harbour site hot-work permit needed forklift-14 work",
            "n1": "inland site hot-work permit needed forklift-14 work",
        }
        need = ["permit", "forklift-14", "harbour", "site", "work"]
        chain = chains.search(list(corpus), terms_of(corpus), need)
        self.assertEqual(chain.memory_ids, ("a1",))


class TestBounds(unittest.TestCase):
    def test_the_search_is_bounded_independently_of_corpus_size(self):
        """Expansion is capped per state, so cost does not track the corpus.

        The budget was once the only bound and expansion scanned every
        candidate for every state in the beam, so one round over 495 candidates
        cost ~3,960 against a budget of 2,000: the search died mid-round and
        returned a one-memory chain.
        """
        big = dict(CHAIN)
        for i in range(600):
            big[f"pad{i}"] = f"depot note {i} canteen weighbridge hi-vis"
        chain = chains.search(list(big), terms_of(big), NEED)
        self.assertTrue(chain.complete)
        self.assertIn("h2", chain.memory_ids)
        self.assertFalse(chain.budget_exhausted)
        self.assertLess(chain.nodes_explored, chains.BEAM * chains.BEAM
                        * chains.MAX_STEPS * 2)

    def test_an_unreachable_term_yields_an_incomplete_chain_naming_it(self):
        chain = chains.search(list(CHAIN), terms_of(CHAIN),
                              NEED + ["unobtainable"])
        self.assertFalse(chain.complete)
        self.assertIn("unobtainable", chain.missing)

    def test_no_candidates_yields_an_empty_chain(self):
        chain = chains.search([], {}, NEED)
        self.assertEqual(chain.steps, ())
        self.assertFalse(chain.complete)

    def test_no_need_yields_an_empty_chain(self):
        chain = chains.search(list(CHAIN), terms_of(CHAIN), [])
        self.assertEqual(chain.steps, ())


class TestItNeverReadsLabels(unittest.TestCase):
    def test_the_module_does_not_reference_benchmark_labels(self):
        """Registered constraint: the mechanism may use content, edges and
        gates, and must not use `critical`, `requirements` or `stale`."""
        source = (ROOT / "memory_fabric" / "chains.py").read_text(encoding="utf-8")
        for forbidden in ('"critical"', '"requirements"', '"stale"', "labels"):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
