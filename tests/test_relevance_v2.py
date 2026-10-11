"""relevance_v2: reproducibility, label integrity, and the falsification arms.

The benchmark is generated rather than committed, so these tests are the
reproducibility claim: they rebuild it into a temporary directory and compare
against the committed manifest digests. If the generator drifts, this fails
before any measurement is taken against the new bytes.

The falsification tests are the other half. v1 shipped two benchmarks that
leaked their own answers -- storage order, then `k` near the corpus size -- and
both times a deliberately broken arm outscored the real baseline before anyone
noticed. A benchmark nobody has tried to break is not evidence.
"""

from __future__ import annotations

import json
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from experiments import relevance_bench as rb  # noqa: E402
from research.bench.relevance_v2 import build  # noqa: E402

BENCH = ROOT / "research" / "bench" / "relevance_v2"
MANIFEST = json.loads((BENCH / "MANIFEST.json").read_text(encoding="utf-8"))
BUILT = (BENCH / "dev.json").exists() and (BENCH / "test.json").exists()
needs_build = unittest.skipUnless(
    BUILT,
    "relevance_v2 is generated; run `python -m research.bench.relevance_v2.build`",
)


class TestReproducible(unittest.TestCase):
    def test_a_rebuild_matches_the_committed_digests(self):
        """Two builds of one commit are byte-identical.

        Written against a temporary directory so the test never depends on, or
        disturbs, whatever is in the working tree.
        """
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            manifest = build.write(pathlib.Path(tmp))
        for split, expected in MANIFEST["splits"].items():
            with self.subTest(split=split):
                self.assertEqual(
                    manifest["splits"][split]["sha256"], expected["sha256"],
                    f"{split} no longer reproduces. If the change is intended, "
                    f"this is a new benchmark directory and a SPEC version "
                    f"bump, not an edited manifest.",
                )

    def test_the_manifest_describes_eleven_families_of_six(self):
        self.assertEqual(MANIFEST["per_family"], 6)
        self.assertEqual(len(MANIFEST["families"]), 11)
        self.assertEqual(sorted(build.BUILDERS), MANIFEST["families"])


class TestLabelIntegrity(unittest.TestCase):
    """The guards in the generator, asserted from outside it.

    `case()` checks these at build time. Checking them again here is not
    duplication: it proves the committed bytes satisfy them, which is what a
    measurement actually reads.
    """

    @needs_build
    def test_no_answer_key_matches_an_irrelevant_memory(self):
        for split in ("dev", "test"):
            for case in rb.load(split, "relevance_v2"):
                keys = case["labels"].get("answer_contains") or []
                relevant = set(case["labels"]["relevant"])
                for memory in case["corpus"]:
                    if memory["id"] in relevant:
                        continue
                    for key in keys:
                        self.assertFalse(
                            build.key_matches(key, memory["content"]),
                            f"{case['case_id']}: {key!r} is answerable from "
                            f"{memory['id']}, which the case calls irrelevant",
                        )

    @needs_build
    def test_every_memory_is_labelled(self):
        for split in ("dev", "test"):
            for case in rb.load(split, "relevance_v2"):
                labelled = set(case["labels"]["relevant"]) | set(
                    case["labels"]["irrelevant"])
                ids = {m["id"] for m in case["corpus"]}
                self.assertEqual(ids - labelled, set(), case["case_id"])

    @needs_build
    def test_parent_edges_are_pairs_naming_a_memory_in_the_corpus(self):
        """The fixture bug that made two whole families inert.

        The harness reads `p[0]` for a parent id. Bare strings made that the
        first character, so no derivation edge survived and every derived
        memory became its own source root.
        """
        seen_any = False
        for split in ("dev", "test"):
            for case in rb.load(split, "relevance_v2"):
                ids = {m["id"] for m in case["corpus"]}
                for memory in case["corpus"]:
                    for parent in memory.get("parents") or ():
                        seen_any = True
                        self.assertIsInstance(parent, list)
                        self.assertEqual(len(parent), 2)
                        self.assertIn(parent[0], ids)
        self.assertTrue(seen_any, "no parent edges at all, which was the bug")

    @needs_build
    def test_the_provenance_families_carry_real_derivation_structure(self):
        """Declared edges are not enough; the store must build the graph.

        Asserted through the product rather than the fixture, because the
        fixture looked correct while the store saw no parents.
        """
        for split in ("dev", "test"):
            for case in rb.load(split, "relevance_v2"):
                if case["family"] != "shared_root":
                    continue
                derived = [m for m in case["corpus"] if m.get("parents")]
                self.assertEqual(len(derived), 4, case["case_id"])
                roots = {m["source_root"] for m in derived}
                self.assertEqual(roots, {"r1"}, case["case_id"])

    @needs_build
    def test_critical_requirements_are_satisfiable_only_by_relevant_memories(self):
        for split in ("dev", "test"):
            for case in rb.load(split, "relevance_v2"):
                relevant = set(case["labels"]["relevant"])
                for req in case["labels"]["requirements"]:
                    if not req.get("critical"):
                        continue
                    self.assertTrue(
                        set(req["satisfied_by"]) <= relevant,
                        f"{case['case_id']}/{req['req_id']}",
                    )


class TestGradingRule(unittest.TestCase):
    def test_a_key_is_not_matched_inside_a_longer_number(self):
        """The bug that made R6's grader wrong on this corpus."""
        self.assertFalse(build.key_matches("4 tonnes", "rated lift is 14 tonnes"))
        self.assertTrue(build.key_matches("4 tonnes", "rated lift is 4 tonnes"))
        self.assertFalse(build.key_matches("14", "assigned to forklift-140"))

    def test_the_no_space_alternative_still_matches(self):
        self.assertTrue(build.key_matches("3.5bar", "inflated to 3.5bar today"))


class TestFalsification(unittest.TestCase):
    """A broken arm must fail, and nothing may beat the ceiling."""

    @needs_build
    def test_an_arm_with_no_relevance_signal_scores_near_zero(self):
        result = rb.run("dev", k=5, arms=["broken_no_signal", "lexical"],
                        benchmark="relevance_v2")
        broken = result["arms"]["broken_no_signal"]["ndcg_at_k"]
        real = result["arms"]["lexical"]["ndcg_at_k"]
        self.assertLess(
            broken, 0.10,
            f"storage order scores {broken:.3f}. On relevance_v1 this arm "
            f"scored 0.843 because k was near the corpus size; if it scores "
            f"again, the corpus is too small or the labels leak position.",
        )
        self.assertGreater(real, broken + 0.3)

    @needs_build
    def test_no_arm_beats_the_oracle(self):
        result = rb.run("dev", k=5, benchmark="relevance_v2",
                        arms=["lexical", "hybrid", "lexical_all", "store_all",
                              "oracle"])
        ceiling = result["arms"]["oracle"]["ndcg_at_k"]
        for name, row in result["arms"].items():
            self.assertLessEqual(
                row["ndcg_at_k"], ceiling + 1e-9,
                f"{name} beat the ceiling, which means the ceiling is wrong "
                f"(principle 8b), not that the arm is good",
            )

    @needs_build
    def test_sufficiency_cannot_be_met_by_a_memory_a_gate_refuses(self):
        """The `gated` family: the only satisfier is capability-gated.

        An arm that reported sufficiency here would be claiming a defensible
        answer built on something it may not expose -- the same error as
        crediting a gate-bypassing arm's nDCG, which once produced 1.090.
        """
        cases = [c for c in rb.load("dev", "relevance_v2") if c["family"] == "gated"]
        self.assertEqual(len(cases), 3)
        for case in cases:
            scored = rb.score_case(case, ["a1"], {}, 5)
            self.assertIs(scored.sufficient, False, case["case_id"])
            self.assertEqual(scored.requirements_met, 0, case["case_id"])


class TestCorpusShape(unittest.TestCase):
    @needs_build
    def test_corpora_are_large_enough_that_reading_them_is_not_a_strategy(self):
        """R6's frozen split abandoned because 19 memories could just be read."""
        for split in ("dev", "test"):
            cases = rb.load(split, "relevance_v2")
            smallest = min(c["corpus_size"] for c in cases)
            self.assertGreater(smallest, 400, f"{split} has a {smallest}-memory case")
            budget = [c for c in cases if c["family"] == "budget_pressure"]
            self.assertTrue(all(c["corpus_tokens"] > 20_000 for c in budget))

    @needs_build
    def test_no_duplicate_content_within_a_case(self):
        """The first build produced 288 ids for 36 distinct sentences."""
        import collections

        for split in ("dev", "test"):
            for case in rb.load(split, "relevance_v2"):
                counts = collections.Counter(m["content"] for m in case["corpus"])
                repeated = [text for text, n in counts.items() if n > 1]
                self.assertEqual(repeated, [], case["case_id"])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
