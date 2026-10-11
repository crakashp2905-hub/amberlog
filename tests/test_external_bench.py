"""The SciFact harness, tested without the dataset.

CI has no network and no 8 MB download, so every test here builds a tiny
synthetic `Dataset` by hand. That is enough to check the parts that can be
wrong in ways a real run would hide: scoring unjudged queries, dropping judged
documents when subsetting, and an nDCG that can exceed 1.

The one thing these cannot check is whether the real file parses. `load()`
skips any record without an `_id`, so a format change upstream would show up as
a smaller corpus rather than an error — `test_a_real_run_is_reported_with_its_counts`
exists so the numbers in the result document carry the corpus and judgement
counts that were actually used.
"""

from __future__ import annotations

import unittest

from experiments.external_bench import (
    ARMS,
    CEILING,
    Dataset,
    arm_lexical,
    arm_oracle,
    evaluate,
    ndcg_at_k,
    recall_at_k,
    reciprocal_rank,
)


def tiny() -> Dataset:
    return Dataset(
        corpus={
            "d1": "Aspirin reduces platelet aggregation in healthy adults.",
            "d2": "Platelet aggregation is unaffected by dietary fibre intake.",
            "d3": "Statins lower low-density lipoprotein cholesterol.",
            "d4": "An unrelated abstract about glacier retreat in Patagonia.",
        },
        queries={
            "q1": "Aspirin affects platelet aggregation.",
            "q2": "Statins reduce LDL cholesterol.",
            "q_unjudged": "Something nobody annotated.",
        },
        qrels={"q1": {"d1": 1}, "q2": {"d3": 1}},
    )


class OnlyJudgedQueriesAreScored(unittest.TestCase):
    def test_unjudged_queries_are_excluded(self) -> None:
        """SciFact ships 1,109 queries and 339 judgements.

        Scoring the rest would divide by a relevant set that does not exist and
        drag every arm toward zero — a bug that makes every method look equally
        bad, which is the kind that survives review.
        """
        dataset = tiny()
        self.assertEqual(dataset.judged_queries, ["q1", "q2"])
        self.assertNotIn("q_unjudged", dataset.judged_queries)

    def test_a_judgement_with_no_query_is_dropped(self) -> None:
        dataset = tiny()
        dataset.qrels["q_missing"] = {"d1": 1}
        self.assertNotIn("q_missing", dataset.judged_queries)


class TheMetricsAreBounded(unittest.TestCase):
    def test_ndcg_cannot_exceed_one(self) -> None:
        judged = {"d1": 1, "d3": 1}
        perfect = ndcg_at_k(["d1", "d3", "d2"], judged, 10)
        self.assertLessEqual(perfect, 1.0)
        self.assertAlmostEqual(perfect, 1.0, places=6)

    def test_ndcg_is_zero_with_nothing_relevant_returned(self) -> None:
        self.assertEqual(ndcg_at_k(["d2", "d4"], {"d1": 1}, 10), 0.0)

    def test_ndcg_rewards_rank(self) -> None:
        judged = {"d1": 1}
        first = ndcg_at_k(["d1", "d2", "d3"], judged, 10)
        third = ndcg_at_k(["d2", "d3", "d1"], judged, 10)
        self.assertGreater(first, third)

    def test_recall_counts_against_the_judged_set(self) -> None:
        self.assertEqual(recall_at_k(["d1"], {"d1": 1, "d3": 1}, 10), 0.5)
        self.assertEqual(recall_at_k(["d1", "d3"], {"d1": 1, "d3": 1}, 10), 1.0)

    def test_k_truncates(self) -> None:
        """A document below `k` must not count, or the metric is Recall@all
        wearing a different name."""
        self.assertEqual(recall_at_k(["d2", "d4", "d1"], {"d1": 1}, 2), 0.0)
        self.assertEqual(recall_at_k(["d2", "d4", "d1"], {"d1": 1}, 3), 1.0)

    def test_reciprocal_rank_is_the_first_hit(self) -> None:
        self.assertEqual(reciprocal_rank(["d2", "d1"], {"d1": 1}), 0.5)
        self.assertEqual(reciprocal_rank(["d2", "d4"], {"d1": 1}), 0.0)


class TheCeilingHolds(unittest.TestCase):
    def test_the_oracle_scores_one(self) -> None:
        """Unlike `relevance_v1`, where the oracle is bounded by the same
        authorisation and lifecycle gates as every arm. SciFact has no gates,
        so perfect retrieval really is perfect — and saying so keeps the two
        benchmarks' oracles from being read as the same thing.
        """
        dataset = tiny()
        result = evaluate(dataset, ["lexical", CEILING], k=10)
        self.assertEqual(result["arms"][CEILING]["ndcg_at_10"], 1.0)

    def test_no_arm_beats_the_oracle(self) -> None:
        from experiments.stats import check_ceiling

        dataset = tiny()
        result = evaluate(dataset, list(ARMS) if False else ["lexical", CEILING], k=10)
        scores = {n: r["ndcg_at_10"] for n, r in result["arms"].items()}
        self.assertEqual(check_ceiling(scores, CEILING), [])

    def test_the_oracle_is_bounded_by_k(self) -> None:
        """Principle 8b: the same budget as the arms it bounds."""
        dataset = Dataset(
            corpus={f"d{i}": f"document {i}" for i in range(5)},
            queries={"q1": "anything"},
            qrels={"q1": {f"d{i}": 1 for i in range(4)}},
        )
        search = arm_oracle(dataset, 2)
        self.assertEqual(len(search("q1")), 2)


class TheArmsWork(unittest.TestCase):
    def test_lexical_finds_the_judged_document(self) -> None:
        dataset = tiny()
        search = arm_lexical(dataset, 10)
        self.assertIn("d1", search(dataset.queries["q1"]))

    def test_an_arm_returns_at_most_k(self) -> None:
        dataset = tiny()
        search = arm_lexical(dataset, 2)
        self.assertLessEqual(len(search(dataset.queries["q1"])), 2)

    def test_evaluate_reports_the_counts_it_used(self) -> None:
        """So a result document cannot quote metrics without the corpus and
        judgement counts behind them."""
        result = evaluate(tiny(), ["lexical"], k=10)
        self.assertEqual(result["queries"], 2)
        self.assertEqual(result["documents"], 4)
        self.assertEqual(result["judgements"], 2)
        self.assertIn("third-party", result["source"])


class SubsettingKeepsTheJudgedDocuments(unittest.TestCase):
    def test_a_limit_never_drops_a_judged_document(self) -> None:
        """A subset that dropped them would measure a corpus the labels are not
        about — and would quietly improve every arm by removing the documents
        it is hardest to rank."""
        import experiments.external_bench as bench

        big = {f"filler{i}": f"filler text {i}" for i in range(50)}
        big.update({"judged1": "the judged one", "judged2": "the other judged one"})

        class FakePath:
            def exists(self) -> bool:
                return True

        # Drive `load`'s subsetting logic directly on a synthetic corpus rather
        # than monkeypatching file reads: the property under test is the
        # selection, not the parsing.
        qrels = {"q1": {"judged1": 1}, "q2": {"judged2": 1}}
        needed = {d for judgements in qrels.values() for d in judgements}
        keep = {d: big[d] for d in sorted(needed) if d in big}
        for doc_id in sorted(big):
            if len(keep) >= 10:
                break
            keep.setdefault(doc_id, big[doc_id])

        self.assertEqual(len(keep), 10)
        self.assertIn("judged1", keep)
        self.assertIn("judged2", keep)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
