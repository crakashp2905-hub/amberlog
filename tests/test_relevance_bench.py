"""The R1 gate: the benchmark must be able to fail.

A benchmark that cannot distinguish a working ranker from a broken one is not
evidence, it is decoration. These tests are mostly about that — the dataset's
own integrity, and the two deliberately broken arms that must land at the
floor.

The gate exists because this benchmark was invalid twice while being built, and
the broken-arm check caught it both times:

1. Cases were written with the relevant memory first, so corpus order was a near-perfect ranking signal: `broken_no_signal` scored **0.869** nDCG against the hybrid baseline's 0.832. Fixed by shuffling the corpus in the generator with a seed derived from the case id.
2. Corpora held 3–5 memories against `k=3`, so every arm returned nearly everything and recall was 1.0 by construction. `broken_no_signal` still scored **0.843**. Fixed by adding 15 shared distractors per case.

Both were failures of the measurement, not the mechanism, which is the pattern
RETROSPECTIVE.md records for three of four simulated hypotheses.
"""

from __future__ import annotations

import unittest

from experiments.relevance_bench import (
    ARMS,
    BROKEN_ARMS,
    CEILING,
    headroom,
    load,
    run,
    to_markdown,
)
from experiments.stats import check_ceiling

SPLITS = ("dev", "test")


class TheDatasetIsWellFormed(unittest.TestCase):
    def test_both_splits_load(self) -> None:
        for split in SPLITS:
            with self.subTest(split):
                self.assertTrue(load(split))

    def test_case_ids_are_unique_across_splits(self) -> None:
        ids = [c["case_id"] for split in SPLITS for c in load(split)]
        self.assertEqual(len(ids), len(set(ids)))

    def test_every_family_is_represented(self) -> None:
        """Fifteen families, each a different way for a retriever to be wrong.
        A family silently dropping out would narrow the benchmark without
        changing any number."""
        families = {c["family"] for split in SPLITS for c in load(split)}
        self.assertEqual(len(families), 15, sorted(families))

    def test_labels_reference_real_memories(self) -> None:
        for split in SPLITS:
            for case in load(split):
                ids = {m["id"] for m in case["corpus"]}
                for key in ("relevant", "critical", "irrelevant", "must_not_expose"):
                    with self.subTest(case=case["case_id"], key=key):
                        self.assertTrue(set(case["labels"][key]) <= ids)

    def test_relevant_and_irrelevant_do_not_overlap(self) -> None:
        for split in SPLITS:
            for case in load(split):
                with self.subTest(case["case_id"]):
                    self.assertFalse(
                        set(case["labels"]["relevant"])
                        & set(case["labels"]["irrelevant"])
                    )

    def test_critical_implies_relevant(self) -> None:
        for split in SPLITS:
            for case in load(split):
                with self.subTest(case["case_id"]):
                    self.assertTrue(
                        set(case["labels"]["critical"])
                        <= set(case["labels"]["relevant"])
                    )

    def test_every_case_carries_a_rationale(self) -> None:
        """A label without a stated reason cannot be reviewed, and the
        labelling rule that matters — never call a memory irrelevant because an
        agent's answer failed — is only checkable if the reason is written
        down."""
        for split in SPLITS:
            for case in load(split):
                with self.subTest(case["case_id"]):
                    self.assertGreater(len(case["rationale"]), 30)

    def test_the_corpus_is_much_larger_than_k(self) -> None:
        """The defect that made the first build meaningless: with k >= corpus
        size, ranking cannot be wrong."""
        for split in SPLITS:
            for case in load(split):
                with self.subTest(case["case_id"]):
                    self.assertGreaterEqual(len(case["corpus"]), 12)

    def test_the_relevant_memory_is_not_always_first(self) -> None:
        """Corpus order must carry no signal.

        It did: the relevant memory led almost every case, and an arm that
        simply returned storage order scored 0.869 nDCG.
        """
        leading = 0
        total = 0
        for split in SPLITS:
            for case in load(split):
                if not case["labels"]["relevant"]:
                    continue
                total += 1
                if case["corpus"][0]["id"] in set(case["labels"]["relevant"]):
                    leading += 1
        self.assertLess(
            leading / total, 0.35, f"{leading}/{total} cases lead with a relevant memory"
        )

    def test_an_unanswerable_case_has_no_relevant_memory(self) -> None:
        for split in SPLITS:
            for case in load(split):
                if case["labels"]["expect_abstain"]:
                    with self.subTest(case["case_id"]):
                        self.assertEqual(case["labels"]["relevant"], [])


class ABrokenRankerFails(unittest.TestCase):
    """The R1 gate proper."""

    def test_an_arm_with_no_relevance_signal_lands_at_the_floor(self) -> None:
        result = run("dev", arms=["broken_no_signal", "lexical", "oracle"])
        broken = result["arms"]["broken_no_signal"]
        real = result["arms"]["lexical"]
        self.assertLess(broken["ndcg_at_k"], 0.1, broken)
        self.assertGreater(real["ndcg_at_k"], 0.5, real)
        # And it does not abstain, so it cannot hide behind the floor the way
        # `none` legitimately does on unanswerable cases.
        self.assertEqual(broken["false_abstention"], 0.0)
        self.assertGreater(broken["irrelevant_ratio"], 0.9)

    def test_bypassing_the_gates_is_detected(self) -> None:
        """`must_not_expose_rate` must be able to fire.

        It can only be non-zero for an arm that skips the gates, because the
        gates are outside the score by design — so without this the metric
        would read 0.000 forever and look like a guarantee.
        """
        clean = run("dev", arms=["oracle"])
        self.assertEqual(clean["arms"]["oracle"]["must_not_expose_rate"], 0.0)

        leaky = run("dev", arms=["broken_bypasses_gates"], bypass_gates=True)
        self.assertGreater(
            leaky["arms"]["broken_bypasses_gates"]["must_not_expose_rate"], 0.0
        )

    def test_bypassing_a_gate_buys_no_ranking_credit(self) -> None:
        """Returning a forbidden memory must cost, never pay.

        Gain is credited for *reachable* relevance only. Crediting it against
        the full relevant set produced an nDCG of 1.090 — an impossible number,
        and a scoring rule that rewarded the one thing an arm must not do.
        """
        leaky = run("dev", arms=["broken_bypasses_gates"], bypass_gates=True)
        for row in leaky["arms"].values():
            with self.subTest(row["arm"]):
                self.assertLessEqual(row["ndcg_at_k"], 1.0)
                self.assertLessEqual(row["precision_at_k"], 1.0)

    def test_the_runner_exits_non_zero_on_a_gate_violation(self) -> None:
        from experiments.relevance_bench import main

        self.assertEqual(main(["--split", "dev"]), 0)
        self.assertEqual(
            main([
                "--split", "dev", "--bypass-gates",
                "--arms", "broken_bypasses_gates", "oracle",
            ]),
            1,
        )


class TheCeilingHolds(unittest.TestCase):
    def test_no_arm_beats_the_oracle(self) -> None:
        """Principle 8b, checked on every run. An arm above the ceiling is not
        a surprising result, it is proof the ceiling is wrong — which this
        project has done three times."""
        for split in SPLITS:
            with self.subTest(split):
                result = run(split)
                scores = {
                    name: row["ndcg_at_k"] for name, row in result["arms"].items()
                }
                self.assertEqual(check_ceiling(scores, CEILING), [])

    def test_the_oracle_leads_on_every_reported_metric(self) -> None:
        result = run("dev")
        oracle = result["arms"][CEILING]
        for name, row in result["arms"].items():
            if name == CEILING:
                continue
            for metric in ("ndcg_at_k", "recall_at_k", "critical_recall"):
                with self.subTest(arm=name, metric=metric):
                    self.assertLessEqual(row[metric], oracle[metric] + 1e-9)

    def test_the_oracle_gets_the_same_k_and_the_same_gates(self) -> None:
        """No handicap the arms lack, and no advantage either.

        Phase A's oracle had a smaller retrieval budget than the arms it
        bounded and scored 100% on the pilot; nobody noticed until an arm beat
        it.
        """
        narrow = run("dev", k=1)
        wide = run("dev", k=5)
        self.assertLess(
            narrow["arms"][CEILING]["recall_at_k"],
            wide["arms"][CEILING]["recall_at_k"],
            "the oracle must be bound by k like every other arm",
        )

    def test_the_headroom_is_reported_against_the_best_simple_baseline(self) -> None:
        """Not against `none`. Requiring improvement over no-memory establishes
        nothing; H2 is the standing precedent, where the cheap baseline already
        captured 93% of the available gain."""
        gap = headroom(run("dev"))
        self.assertNotEqual(gap["best_simple_arm"], "none")
        self.assertNotEqual(gap["best_simple_arm"], CEILING)
        self.assertGreater(gap["best_simple"], 0.0)
        self.assertAlmostEqual(
            gap["headroom"], gap["ceiling"] - gap["best_simple"], places=4
        )


class ItIsReproducible(unittest.TestCase):
    def test_two_runs_agree_exactly(self) -> None:
        """No model calls and no sampling, so a difference between runs would
        mean a hidden source of state."""
        first = run("dev")
        second = run("dev")
        self.assertEqual(first["arms"], second["arms"])
        self.assertEqual(first["by_family"], second["by_family"])

    def test_the_markdown_report_is_byte_identical_across_runs(self) -> None:
        self.assertEqual(to_markdown(run("dev")), to_markdown(run("dev")))

    def test_every_arm_runs_on_both_splits(self) -> None:
        for split in SPLITS:
            result = run(split)
            with self.subTest(split):
                self.assertEqual(set(result["arms"]), set(ARMS))

    def test_the_broken_arms_are_not_in_the_default_set(self) -> None:
        """A normal run must not be able to include one by accident."""
        self.assertFalse(set(BROKEN_ARMS) & set(ARMS))
        self.assertEqual(set(run("dev")["arms"]), set(ARMS))


class TheProductArmImproved(unittest.TestCase):
    """Pins the retrieval change R1 motivated, so a regression is visible.

    `relevance_v1` found the shipping vector path to be the weakest non-broken
    arm. Hybrid retrieval (RRF over the vector and lexical indexes) is now the
    default, and `store_vector` pins the old behaviour so the comparison stays
    measurable rather than remembered.
    """

    def test_hybrid_beats_the_old_vector_only_path(self) -> None:
        for split in SPLITS:
            result = run(split, arms=["current", "store_vector"])
            with self.subTest(split):
                self.assertGreater(
                    result["arms"]["current"]["ndcg_at_k"],
                    result["arms"]["store_vector"]["ndcg_at_k"],
                )

    def test_it_omits_fewer_critical_memories(self) -> None:
        """The metric the default was chosen for. Lexical alone has a better
        nDCG; hybrid misses the decisive memory less often, and that is the
        failure with a consequence."""
        for split in SPLITS:
            result = run(split, arms=["current", "store_vector"])
            with self.subTest(split):
                self.assertLessEqual(
                    result["arms"]["current"]["critical_omission_rate"],
                    result["arms"]["store_vector"]["critical_omission_rate"],
                )

    def test_the_old_behaviour_is_still_reachable(self) -> None:
        """`retrieval="vector"` reproduces the pre-change ranking exactly, for
        anyone who needs the old ordering while validating."""
        result = run("test", arms=["store_vector", "vector"])
        self.assertEqual(
            result["arms"]["store_vector"]["ndcg_at_k"],
            result["arms"]["vector"]["ndcg_at_k"],
        )

    def test_an_unknown_retrieval_mode_is_refused(self) -> None:
        from memory_fabric import MemoryFabric

        fabric = MemoryFabric(":memory:", retrieval="magic")
        self.addCleanup(fabric.close)
        with self.assertRaises(ValueError):
            fabric.retrieve(agent_id="a", query="anything")


class TheFamiliesDiscriminate(unittest.TestCase):
    """A family where every arm scores the same tests nothing."""

    def test_the_oracle_separates_from_the_baselines_somewhere(self) -> None:
        result = run("dev")
        oracle = result["by_family"][CEILING]
        lexical = result["by_family"]["lexical"]
        separated = [
            family
            for family in oracle
            if oracle[family]["ndcg"] is not None
            and lexical[family]["ndcg"] is not None
            and oracle[family]["ndcg"] - lexical[family]["ndcg"] > 0.1
        ]
        self.assertGreaterEqual(
            len(separated), 4,
            f"only {separated} discriminate; the benchmark is too easy",
        )

    def test_the_unanswerable_family_rewards_abstention(self) -> None:
        result = run("dev", arms=["none", "lexical", "oracle"])
        self.assertEqual(result["arms"]["none"]["abstention_precision"], 1.0)
        self.assertEqual(result["arms"]["lexical"]["abstention_precision"], 0.0)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
