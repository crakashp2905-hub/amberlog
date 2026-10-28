"""The benchmark harness itself: registry, manifests, statistics, checks, cost ledger, scoreboard."""

from __future__ import annotations

import random
import tempfile
import unittest
from pathlib import Path

from benchmarks import checks, cost, manifest, registry, scoreboard, stats


class Registry(unittest.TestCase):
    def test_registry_is_valid(self) -> None:
        self.assertEqual(registry.validate(registry.load()), [])

    def test_every_masterplan_suite_is_registered(self) -> None:
        ids = {s["id"] for s in registry.load()["suites"]}
        self.assertEqual(ids, {f"PUB-{i:02d}" for i in range(1, 16)} | {f"INT-{i:02d}" for i in range(1, 11)})

    def test_vendor_arithmetic_disagreements_are_reported(self) -> None:
        found = " ".join(registry.notes(registry.load()))
        self.assertIn("PUB-03", found)   # stated 61.38%, totals give 61.30%
        self.assertIn("PUB-04", found)   # stated 33.09%, totals give 31.63%
        self.assertNotIn("PUB-02", found)  # "about 64%" is within its own rounding

    def test_a_not_run_suite_needs_a_reason(self) -> None:
        bad = {"suites": [{**registry.load()["suites"][0], "run_status": "NOT_RUN", "reason": ""}]}
        self.assertTrue(registry.validate(bad))


class Manifests(unittest.TestCase):
    def test_pass_needs_baseline_oracle_and_prereg(self) -> None:
        m = manifest.Manifest("r", "INT-03", "typed", "PASS", repo_commit="abc")
        self.assertTrue(manifest.validate(m))
        m.verification.update(baseline_registered=True, oracle_sanity_passed=True)
        m.prereg = "research/prereg/x.md"
        self.assertEqual(manifest.validate(m), [])

    def test_not_run_needs_a_reason_and_a_run_needs_a_commit(self) -> None:
        self.assertTrue(manifest.validate(manifest.Manifest("r", "PUB-01", "x", "NOT_RUN")))
        self.assertTrue(manifest.validate(manifest.Manifest("r", "PUB-01", "x", "FAIL")))
        self.assertEqual(manifest.validate(manifest.Manifest("r", "PUB-01", "x", "NOT_RUN", reason="licence")), [])

    def test_cost_per_safe_success_without_one_is_refused(self) -> None:
        m = manifest.Manifest("r", "X", "a", "FAIL", repo_commit="abc", cost={"cost_per_safe_success": 1.0})
        self.assertTrue(manifest.validate(m))

    def test_write_and_read(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            manifest.write(manifest.Manifest("r1", "X", "a", "NOT_RUN", reason="why"), Path(d))
            self.assertEqual(manifest.read_all(Path(d))[0]["run_id"], "r1")
            with self.assertRaises(ValueError):
                manifest.write(manifest.Manifest("r2", "X", "a", "WON"), Path(d))

    def test_recorded_runs_are_valid(self) -> None:
        for m in manifest.read_all():
            self.assertEqual(manifest.validate(m), [], m["run_id"])


class Stats(unittest.TestCase):
    def test_bootstrap_brackets_a_known_difference(self) -> None:
        rng = random.Random(3)
        a = [rng.random() for _ in range(200)]
        b = [x + 0.1 for x in a]
        r = stats.paired_bootstrap(a, b, seed=1)
        self.assertAlmostEqual(r["diff"], 0.1)
        self.assertLessEqual(r["lo"], 0.1 + 1e-9)
        self.assertGreaterEqual(r["hi"], 0.1 - 1e-9)
        self.assertEqual(stats.paired_bootstrap(a, b, seed=1), r)   # seeded

    def test_clusters_widen_the_interval(self) -> None:
        rng = random.Random(5)
        a = [0.0] * 100
        b = [v for v in (rng.choice([-1.0, 1.0]) for _ in range(10)) for _ in range(10)]
        flat = stats.paired_bootstrap(a, b, seed=2)
        grouped = stats.paired_bootstrap(a, b, seed=2, clusters=[i // 10 for i in range(100)])
        self.assertGreater(grouped["hi"] - grouped["lo"], flat["hi"] - flat["lo"])

    def test_zero_events_bound_is_the_rule_of_three(self) -> None:
        self.assertAlmostEqual(stats.zero_events_upper(100), 0.0295, places=3)
        self.assertEqual(stats.zero_events_upper(0), 1.0)

    def test_wilson_holm_sign_kappa(self) -> None:
        lo, hi = stats.wilson(0, 20)
        self.assertEqual(lo, 0.0)
        self.assertGreater(hi, 0.1)
        self.assertEqual(stats.holm([0.001, 0.04, 0.03]), [True, False, False])
        self.assertAlmostEqual(stats.sign_test_p([1] * 10), 2 / 1024)
        self.assertEqual(stats.cohen_kappa("aabb", "aabb"), 1.0)
        self.assertLess(stats.cohen_kappa("abab", "aabb"), 0.5)


class Checks(unittest.TestCase):
    def test_8a_to_8c(self) -> None:
        self.assertAlmostEqual(checks.bar(0.5, 1.0, 0.4), 0.7)
        self.assertFalse(checks.headroom_ok(0.99, 1.0))
        self.assertEqual(checks.arms_above_oracle({"oracle": 0.8, "x": 0.9}), ["x"])
        s = checks.sanity({"oracle": 0.8, "lexical": 0.8, "x": 0.5}, ["lexical"])
        self.assertEqual(s["baselines_at_ceiling"], ["lexical"])
        self.assertFalse(s["ok"])

    def test_8d_baseline_provenance(self) -> None:
        p = {"measured_in_this_run": True, "metric": "set_exact", "k": 50, "split": "test"}
        self.assertTrue(checks.baseline_measured(p, "set_exact", 50, "test"))
        self.assertFalse(checks.baseline_measured(p, "set_exact", 5, "test"))


class Cost(unittest.TestCase):
    def test_total_and_safe_success(self) -> None:
        led = cost.Ledger(ingest=10, query_inference=0.5, storage=2)
        self.assertEqual(led.total(10), 10 + 5 + 2)
        self.assertIsNone(cost.cost_per_safe_success(17, 0))
        self.assertEqual(cost.cost_per_safe_success(17, 17), 1)

    def test_break_even(self) -> None:
        compiled = cost.Ledger(ontology_build=100, query_inference=0.1)
        plain = cost.Ledger(query_inference=0.6)
        self.assertEqual(cost.break_even_queries(compiled, plain), 201)
        self.assertIsNone(cost.break_even_queries(cost.Ledger(index=5, retrieval=1), cost.Ledger(retrieval=1)))


class Scoreboard(unittest.TestCase):
    def test_is_current(self) -> None:
        self.assertEqual(scoreboard.OUT.read_text(encoding="utf-8"), scoreboard.render(),
                         "regenerate: python -m benchmarks.scoreboard --write")

    def test_vendor_numbers_never_land_in_our_column(self) -> None:
        for line in scoreboard.render().splitlines():
            if line.startswith("| PUB-0"):
                ours = line.split("|")[4]
                self.assertNotIn("%", ours)


if __name__ == "__main__":
    unittest.main()


class PersonaMemHelpers(unittest.TestCase):
    def test_parsing_and_budget(self) -> None:
        from benchmarks import personamem as pm

        self.assertEqual(pm.options_of("['(a) tea', '(b) coffee']"), ["(a) tea", "(b) coffee"])
        self.assertEqual(pm.letter("The answer is (B)."), "b")
        self.assertIsNone(pm.letter("no idea"))
        self.assertEqual(len(pm.fit(["one two three", "four five"], 4).split()), 4)
        rows = [{"question_type": t, "i": str(i)} for t in "xyz" for i in range(10)]
        picked = pm.sample(rows, 6)
        self.assertEqual(len(picked), 6)
        self.assertEqual(sorted({r["question_type"] for r in picked}), ["x", "y", "z"])
        self.assertEqual(pm.sample(rows, 6), picked)   # seeded


class BrightScoring(unittest.TestCase):
    def test_bm25_ndcg_recall(self) -> None:
        from benchmarks.bright_pro import BM25, ndcg, recall

        docs = {"a": "the heart pumps blood through arteries", "b": "plants make sugar from light",
                "c": "blood pressure and the heart rate", "d": "rocks erode over time"}
        ranked = BM25(docs).search("heart blood", 4)
        self.assertEqual(set(ranked[:2]), {"a", "c"})
        self.assertNotIn("d", ranked)
        self.assertAlmostEqual(ndcg(["a", "c"], {"a", "c"}), 1.0)
        self.assertAlmostEqual(ndcg(["x", "a"], {"a"}), 1 / __import__("math").log2(3))
        self.assertEqual(recall(["a", "x"], {"a", "c"}, 10), 0.5)
