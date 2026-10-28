import unittest

from benchmarks.completeness_data import SPLITS, digest, generate
from benchmarks.evidence_completeness import evaluate, run_seed
from memory_fabric import MemoryFabric
from memory_fabric.evidence_completeness import exhaustive


class EvaluationTests(unittest.TestCase):
    def test_frozen_seeds_are_disjoint_and_digests_repeat(self):
        self.assertFalse(set(SPLITS["dev"]) & set(SPLITS["test"]))
        self.assertEqual(digest("dev"), "043a07f82c0a3da3c473fbdb2bbbdd1d9caac379fc0aa36ae36c7550885d518a")
        self.assertNotEqual(digest("dev"), digest("test"))

    def test_positive_certificates_match_independent_gold_at_full_diagnostic_budget(self):
        # Not the registered primary read budget. This is a certificate audit:
        # asserting some True certificates prevents an always-incomplete pass.
        f = MemoryFabric(":memory:", recognise_copies=False)
        self.addCleanup(f.close)
        data = generate(101, "test")
        mapping = {}
        for row in data["records"]:
            mid = f.remember("writer", row["text"], structured=row["fields"],
                             auto_activate=True, scope="team")
            mapping[mid] = row["rid"]
        for query, gold in zip(data["queries"], data["gold"]):
            result = exhaustive(f, "reader", query, query="inspection", evaluate=evaluate,
                                evaluator_id="key-value/1", max_reads=48)
            self.assertTrue(result.complete)
            self.assertEqual({mapping[m] for m in result.ids}, set(gold))
            self.assertTrue(result.certificate()["corpus_sha256"])

    def test_oracle_never_exceeds_content_budget_or_loses_to_baselines(self):
        result = run_seed(11, "dev", ("lexical", "typed", "typed+fallback", "selective", "oracle"))
        for arm, rows in result.items():
            for i, row in enumerate(rows):
                self.assertLessEqual(row["reads"], 12)
                self.assertFalse(row["false_complete"])
                self.assertGreaterEqual(result["oracle"][i]["exact"], row["exact"])
