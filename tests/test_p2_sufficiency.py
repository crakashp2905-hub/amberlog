"""P2 — the arms, the verdict arithmetic, and the two defects it shipped with.

The experiment was abandoned on a metric flaw and its selector has a structural
one. Both are asserted here, so that a later change which fixes either has to
notice it is doing so rather than quietly moving a number.
"""

from __future__ import annotations

import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from experiments import p2_sufficiency as p2  # noqa: E402
from experiments import relevance_bench as rb  # noqa: E402

BENCH = ROOT / "research" / "bench" / "relevance_v2"
BUILT = (BENCH / "dev.json").exists()
needs_build = unittest.skipUnless(
    BUILT, "run `python -m research.bench.relevance_v2.build`")


class TestVerdict(unittest.TestCase):
    def _result(self, sufficient: dict[str, float]) -> dict:
        return {"arms": {n: {"sufficient": v} for n, v in sufficient.items()}}

    def test_a_baseline_tying_the_ceiling_is_abandoned(self):
        """The measured shape: `full_context` contains every satisfier.

        Registering sufficiency as primary while registering `full_context` as
        a baseline makes the threshold unreachable before any method exists.
        The clause has to fire rather than the margin being renegotiated.
        """
        v = p2.verdict(self._result({
            "top_k": 0.533, "budget_matched_top_k": 0.533,
            "full_context": 0.800, "sufficiency_aware": 0.533,
            "oracle_evidence": 0.800,
        }))
        self.assertEqual(v["verdict"], "ABANDONED")
        self.assertEqual(v["headroom"], 0.0)

    def test_an_arm_above_the_ceiling_indicts_the_ceiling(self):
        v = p2.verdict(self._result({
            "top_k": 0.4, "budget_matched_top_k": 0.4, "full_context": 0.5,
            "sufficiency_aware": 0.95, "oracle_evidence": 0.8,
        }))
        self.assertIn("CEILING BREACHED", v["verdict"])

    def test_the_threshold_is_a_share_of_headroom_not_a_margin(self):
        v = p2.verdict(self._result({
            "top_k": 0.4, "budget_matched_top_k": 0.4, "full_context": 0.4,
            "sufficiency_aware": 0.6, "oracle_evidence": 0.9,
        }))
        self.assertAlmostEqual(v["threshold"], 0.4 + 0.4 * 0.5, places=6)
        self.assertEqual(v["verdict"], "SUPPORTED")

    def test_below_every_baseline_is_killed_not_merely_unsupported(self):
        v = p2.verdict(self._result({
            "top_k": 0.4, "budget_matched_top_k": 0.4, "full_context": 0.4,
            "sufficiency_aware": 0.2, "oracle_evidence": 0.9,
        }))
        self.assertTrue(v["verdict"].startswith("KILLED"))


class TestCoverage(unittest.TestCase):
    def test_a_query_term_absent_from_the_corpus_is_not_required(self):
        """The defect that abstained on 79% of answerable cases.

        "How often is the cable swapped?" asks for tokens the corpus never
        uses, so demanding them made coverage unreachable by construction.
        """
        case = {
            "task": {"task_text": "How often is the cable swapped at coastal?",
                     "entities": []},
        }
        ctx = p2.Context(
            case=case, fabric=None, store_id={}, bench_id={}, retracted=set(),
            terms={"m1": p2.terms("At coastal, swap the cable every 90 days.")},
        )
        need = p2.reachable_terms(case, ctx, ["m1"])
        self.assertIn("coastal", need)
        self.assertIn("cable", need)
        self.assertNotIn("often", need)
        self.assertNotIn("swapped", need)

    def test_jaccard_separates_a_restatement_from_a_different_predicate(self):
        near = p2.terms("crane-5 tyre pressure at the coastal site is 3.5 bar in winter.")
        twin = p2.terms("crane-5 tyre pressure at the coastal site is 4.2 bar in winter.")
        other = p2.terms("Bay 7 at the coastal site is assigned to tug-3.")
        self.assertGreater(p2.jaccard(near, twin), p2.RESTATEMENT)
        self.assertLess(p2.jaccard(near, other), p2.RESTATEMENT)


class TestPoolIsTheCorpus(unittest.TestCase):
    @needs_build
    def test_a_chain_hop_the_index_cannot_score_is_still_a_candidate(self):
        """Principle 8b: the first run's oracle scored 0.000 on multi-hop.

        Hop 2 shares no term with the query, so `retrieve` never returned it
        and no arm — including the one handed the answers — could select it.
        """
        case = next(c for c in rb.load("dev", "relevance_v2")
                    if c["family"] == "multi_hop_3")
        ctx = p2.build_context(case)
        try:
            pool = p2.base_ranking(ctx)
            for hop in ("h1", "h2", "h3"):
                self.assertIn(hop, pool, f"{case['case_id']}: {hop} unreachable")
            # And a quarantined memory must stay out: the gates decide.
            blocked = [m["id"] for m in case["corpus"]
                       if m["lifecycle_state"] in rb.BLOCKED_LIFECYCLE]
            for memory in blocked:
                self.assertNotIn(memory, pool)
        finally:
            ctx.fabric.close()

    @needs_build
    def test_the_oracle_reaches_every_chain_hop(self):
        case = next(c for c in rb.load("dev", "relevance_v2")
                    if c["family"] == "multi_hop_4")
        ctx = p2.build_context(case)
        try:
            pool = p2.base_ranking(ctx)
            allowed, _ = rb.apply_gates(case, pool)
            assembly = p2.arm_oracle_evidence(case, allowed, ctx, 5)
            outcome = p2.score(case, assembly, 0.0)
            self.assertIs(outcome.sufficient, True, case["case_id"])
        finally:
            ctx.fabric.close()


class TestKnownDefects(unittest.TestCase):
    """Asserted so a fix cannot land silently."""

    @needs_build
    def test_the_selector_still_cannot_assemble_a_chain(self):
        """A connector hop has zero marginal query-term coverage.

        If this starts failing, the selector gained the ability to value a
        bridging memory, which is a result and needs a write-up -- not a test
        to be deleted.
        """
        case = next(c for c in rb.load("dev", "relevance_v2")
                    if c["family"] == "multi_hop_3")
        ctx = p2.build_context(case)
        try:
            allowed, _ = rb.apply_gates(case, p2.base_ranking(ctx))
            assembly = p2.arm_sufficiency_aware(case, allowed, ctx, 5)
            self.assertNotIn(
                "h2", assembly.selected,
                "the selector now selects the connector hop -- see "
                "research/results/p2-context-sufficiency.md section 4",
            )
        finally:
            ctx.fabric.close()

    @needs_build
    def test_the_selector_cites_no_stale_evidence(self):
        """The one effect that replicated on both splits, borrowed from P3."""
        for split in ("dev", "test"):
            for case in rb.load(split, "relevance_v2"):
                if not (case["labels"].get("stale") or ()):
                    continue
                ctx = p2.build_context(case)
                try:
                    allowed, _ = rb.apply_gates(case, p2.base_ranking(ctx))
                    assembly = p2.arm_sufficiency_aware(case, allowed, ctx, 5)
                    outcome = p2.score(case, assembly, 0.0)
                    self.assertEqual(outcome.stale_cited, 0, case["case_id"])
                finally:
                    ctx.fabric.close()


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
