"""propagation_v1 and the P3 arms.

The fixture's whole value is that its derivation chains survive the round trip
into the store. Two runs of P3 were invalid before this file existed: the first
because relevance_v2's pair could not separate the rules, the second because a
non-topological write order dropped the edges in silence and a correct arm
looked wrong. These tests assert the chains, the rules, and the verdict
arithmetic.
"""

from __future__ import annotations

import json
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from experiments import p3_propagation as p3  # noqa: E402
from experiments import relevance_bench as rb  # noqa: E402
from research.bench.propagation_v1 import build  # noqa: E402

BENCH = ROOT / "research" / "bench" / "propagation_v1"
MANIFEST = json.loads((BENCH / "MANIFEST.json").read_text(encoding="utf-8"))
BUILT = (BENCH / "dev.json").exists() and (BENCH / "test.json").exists()
needs_build = unittest.skipUnless(
    BUILT, "run `python -m research.bench.propagation_v1.build`")

# The declared depth of each family's longest chain, asserted through the store
# rather than read off the fixture.
CHAIN_DEPTH = {
    "retracted_intermediate": 2,   # r1 -> s1 -> d1
    "deep_chain": 3,               # r1 -> a1 -> b1 -> c1
    "copied_document": 1,          # r2 -> d1
    "independent_reconfirmation": 1,
}


class TestReproducible(unittest.TestCase):
    def test_a_rebuild_matches_the_committed_digests(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            manifest = build.write(pathlib.Path(tmp))
        for split, expected in MANIFEST["splits"].items():
            with self.subTest(split=split):
                self.assertEqual(manifest["splits"][split]["sha256"],
                                 expected["sha256"])


class TestInsertionOrder(unittest.TestCase):
    """`len(parents)` is not a topological order."""

    def test_a_two_level_chain_is_ordered_by_dependency(self):
        corpus = [
            {"id": "c", "parents": [["b", 1]]},
            {"id": "b", "parents": [["a", 1]]},
            {"id": "a", "parents": []},
        ]
        order = [m["id"] for m in rb.insertion_order(corpus)]
        self.assertLess(order.index("a"), order.index("b"))
        self.assertLess(order.index("b"), order.index("c"))

    def test_sorting_by_parent_count_would_not_have_caught_this(self):
        """The regression itself, stated as a test.

        Both `b` and `c` have one parent, so the old key leaves them in corpus
        order and `c` is written before its parent exists.
        """
        corpus = [
            {"id": "c", "parents": [["b", 1]]},
            {"id": "b", "parents": [["a", 1]]},
            {"id": "a", "parents": []},
        ]
        old = [m["id"] for m in sorted(corpus, key=lambda m: len(m["parents"]))]
        self.assertLess(old.index("c"), old.index("b"))

    def test_a_dangling_parent_raises_rather_than_dropping_the_edge(self):
        with self.assertRaises(AssertionError):
            rb.insertion_order([{"id": "x", "parents": [["missing", 1]]}])


class TestChainsSurviveTheStore(unittest.TestCase):
    @needs_build
    def test_every_family_keeps_its_declared_depth(self):
        for split in ("dev", "test"):
            for case in rb.load(split, "propagation_v1"):
                ctx = p3.build_context(case)
                try:
                    graph = ctx.fabric.lineage_graph
                    deepest = 0
                    for bench, sid in ctx.store_id.items():
                        depth = len([
                            n for n in graph.ancestors(sid)
                            if n.memory_id in ctx.bench_id
                        ])
                        deepest = max(deepest, depth)
                    self.assertEqual(
                        deepest, CHAIN_DEPTH[case["family"]],
                        f"{case['case_id']}: chain depth {deepest}, expected "
                        f"{CHAIN_DEPTH[case['family']]}. A dropped parent edge "
                        f"makes every propagation rule read a derived memory as "
                        f"independent evidence.",
                    )
                finally:
                    ctx.fabric.close()

    @needs_build
    def test_the_retracted_memory_is_an_intermediate_not_a_root(self):
        """The structure relevance_v2 was missing, asserted here."""
        for split in ("dev", "test"):
            for case in rb.load(split, "propagation_v1"):
                if case["family"] != "retracted_intermediate":
                    continue
                ctx = p3.build_context(case)
                try:
                    self.assertEqual(ctx.retracted, {"s1"}, case["case_id"])
                    # Retracted, yet shares a root with standing evidence.
                    self.assertEqual(ctx.root_of("s1"), "r1")
                    self.assertEqual(ctx.root_of("g1"), "r1")
                    self.assertTrue(ctx.has_retracted_ancestor("d1"))
                    self.assertFalse(ctx.has_retracted_ancestor("g1"))
                finally:
                    ctx.fabric.close()


class TestFixtureReproducesTheProductState(unittest.TestCase):
    """The defect that produced a false negative result about shipped behaviour.

    `quarantine(propagate=True)` contests descendants, and CONTESTED is
    withheld by default. Quarantining inside the write loop leaves a retracted
    parent with **active** descendants -- a state the product never puts itself
    in -- and every arm measured against it reports stale citations the product
    does not make. That is how P3 came to conclude that graph traversal beats
    the product, and that the retrieval path has no propagation at all.

    A fixture that does not reproduce the state the product produces measures
    the fixture.
    """

    @needs_build
    def test_descendants_of_a_retracted_memory_are_contested(self):
        from amberlog.model import LifecycleState

        checked = 0
        for split in ("dev", "test"):
            for case in rb.load(split, "propagation_v1"):
                stale = case["labels"].get("stale") or ()
                if not stale:
                    continue
                ctx = p3.build_context(case)
                try:
                    for memory in stale:
                        if memory not in ctx.store_id:
                            continue
                        # `copied_document`'s stale memories descend from a
                        # *different* root, so no propagation reaches them --
                        # which is the family's whole point.
                        if not ctx.has_retracted_ancestor(memory):
                            continue
                        state = ctx.fabric.state.memories[
                            ctx.store_id[memory]].lifecycle_state
                        self.assertEqual(
                            state, LifecycleState.CONTESTED,
                            f"{case['case_id']}/{memory} is {state.value}; the "
                            f"fixture quarantined before this memory existed, so "
                            f"the product's propagation never ran",
                        )
                        checked += 1
                finally:
                    ctx.fabric.close()
        self.assertGreater(checked, 0, "no descendant was checked")

    @needs_build
    def test_the_product_withholds_the_restatements_and_keeps_the_conclusion(self):
        """What P3 said the product could not do.

        The retracted memory is an intermediate: its restatements must go and
        the sibling conclusion drawn from the same standing root must stay.
        """
        for split in ("dev", "test"):
            for case in rb.load(split, "propagation_v1"):
                if case["family"] != "retracted_intermediate":
                    continue
                ctx = p3.build_context(case)
                try:
                    pool = p3.base_ranking(ctx)
                    self.assertIn("g1", pool, case["case_id"])
                    self.assertNotIn("d1", pool, case["case_id"])
                    self.assertNotIn("d2", pool, case["case_id"])
                    self.assertNotIn("s1", pool, case["case_id"])
                finally:
                    ctx.fabric.close()


class TestRules(unittest.TestCase):
    @needs_build
    def test_blanket_invalidation_discards_the_standing_conclusion(self):
        """The failure the fixture exists to catch, and the one real finding.

        g1 does not descend from the retracted interim analysis but shares a
        root with it, so withholding by root identity loses the answer. This is
        the only arm the corrected run separates: the product and
        `graph_traversal` score identically on every metric, because they
        compute the same thing and the product computes it at write time.
        """
        for split in ("dev", "test"):
            for case in rb.load(split, "propagation_v1"):
                if case["family"] != "retracted_intermediate":
                    continue
                ctx = p3.build_context(case)
                try:
                    ranked = p3.base_ranking(ctx)
                    blanket = p3.rule_blanket_invalidation(list(ranked), ctx)
                    traversal = p3.rule_graph_traversal(list(ranked), ctx)
                    self.assertNotIn("g1", blanket, case["case_id"])
                    self.assertIn("g1", traversal, case["case_id"])
                    self.assertNotIn("d1", traversal, case["case_id"])
                finally:
                    ctx.fabric.close()

    @needs_build
    def test_a_re_ingested_document_is_recognised_at_write_time(self):
        """The replacement for `test_no_rule_solves_a_re_ingested_document`.

        That test asserted no rule could see a copy filed under its own root,
        and carried the note: *if a change makes this fail, the product gained
        the ability, which is a result and needs its own write-up -- not a test
        to be deleted.* It failed. The write-up is
        `research/results/p2b-copy-recognition.md`, and this is the inverted
        assertion.

        The recognition happens at **write** time, not in any propagation rule,
        which is why none of the rules could ever have solved it: by the time
        they run there are two roots, and the question is whether there should
        have been one.
        """
        for split in ("dev", "test"):
            for case in rb.load(split, "propagation_v1"):
                if case["family"] != "copied_document":
                    continue
                ctx = p3.build_context(case)
                try:
                    fabric = ctx.fabric
                    r1, r2 = ctx.store_id["r1"], ctx.store_id["r2"]
                    # Direction is not asserted. The recorded edge runs from
                    # the newer write to the older one, and these corpora are
                    # shuffled, so which of the two is "the copy" depends on
                    # storage order. What must hold is that they are the same
                    # document, which is symmetric.
                    related = (fabric.state.copy_of.get(r2) == r1
                               or fabric.state.copy_of.get(r1) == r2)
                    self.assertTrue(
                        related,
                        f"{case['case_id']}: the re-ingestion was not recognised")
                    self.assertEqual(
                        fabric.source_root(r2), fabric.source_root(r1),
                        f"{case['case_id']}: copy and original must share a root")
                    # The original is withdrawn, so the copy may not be exposed.
                    self.assertNotIn("r2", p3.base_ranking(ctx),
                                     case["case_id"])
                finally:
                    ctx.fabric.close()

    def test_the_oracle_is_the_only_rule_that_reads_the_labels(self):
        import inspect

        for name, rule in p3.RULES.items():
            source = inspect.getsource(rule)
            if name == p3.CEILING:
                continue
            self.assertNotIn(
                '["labels"]', source,
                f"{name} reads the labels, which makes it an oracle rather "
                f"than a method",
            )


class TestVerdict(unittest.TestCase):
    """The registered arithmetic, including the clause that fired once."""

    def _result(self, stale: dict[str, float], invalid: float = 0.0) -> dict:
        return {
            "arms": {
                name: {
                    "stale_citations_mean": value,
                    "unnecessary_invalidation": (
                        invalid if name == "blanket_invalidation" else 0.0),
                }
                for name, value in stale.items()
            }
        }

    def test_zero_headroom_is_abandoned_not_reinterpreted(self):
        v = p3.verdict(self._result({
            "no_propagation": 3.333, "blanket_invalidation": 0.0,
            "graph_traversal": 0.0, "source_root_grouping": 1.0,
            "oracle_propagation": 0.0,
        }))
        self.assertEqual(v["verdict"], "ABANDONED")

    def test_the_measured_dev_shape_is_not_supported(self):
        v = p3.verdict(self._result({
            "no_propagation": 1.375, "blanket_invalidation": 0.5,
            "graph_traversal": 0.5, "source_root_grouping": 1.25,
            "oracle_propagation": 0.0,
        }))
        self.assertEqual(v["verdict"], "NOT SUPPORTED")
        self.assertAlmostEqual(v["threshold"], 0.300, places=3)

    def test_trading_invalidation_for_stale_citations_fails_outright(self):
        """A rule cannot buy the primary metric with the secondary one."""
        result = self._result({
            "no_propagation": 1.375, "blanket_invalidation": 0.5,
            "graph_traversal": 0.5, "source_root_grouping": 0.1,
            "oracle_propagation": 0.0,
        })
        result["arms"]["source_root_grouping"]["unnecessary_invalidation"] = 0.9
        v = p3.verdict(result)
        self.assertTrue(v["verdict"].startswith("FAILED"))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
