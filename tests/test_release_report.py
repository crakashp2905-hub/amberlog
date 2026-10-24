"""The release report is rendered from the bundle alone, and the product benchmark measures what it says."""

from __future__ import annotations

import json
import random
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from experiments import product_bench  # noqa: E402
from release_report import render  # noqa: E402


class ReleaseReport(unittest.TestCase):
    def test_every_section_comes_from_a_bundle_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bundle = Path(tmp)
            (bundle / "manifest.json").write_text(json.dumps({
                "commit": "abcdef1234567890", "dirty": False, "package_version": "9.9",
                "schema_version": "9.9", "python": "3.13", "platform": "x", "built_at": "t",
                "checks": {"secret scan": True, "tests": False}, "files": {"tests.json": "0" * 64}}))
            (bundle / "tests.json").write_text(json.dumps(
                {"run": 12, "skipped": 1, "failures": ["t"], "errors": [], "passed": False}))
            point = product_bench.measure(80, seed=1, queries=10)
            (bundle / "product-bench.json").write_text(json.dumps(
                {"seed": 1, "quick": True, "points": [point]}))
            page = render(bundle)
        self.assertIn("# Release report: `abcdef123456`", page)
        self.assertIn("| tests | **FAIL** |", page)
        self.assertIn("**12** run, 1 skipped, 1 failures", page)
        self.assertIn("| 80 | ", page)
        self.assertNotIn("dirty tree", page)


class ProductBench(unittest.TestCase):
    def test_a_planted_tag_is_named_by_other_notes_too(self) -> None:
        """Otherwise the tag alone finds the fact and recall measures nothing."""
        notes, planted = product_bench.corpus(400, random.Random(3))
        tag = planted[5][1].split(" for ")[1].split()[1]
        self.assertGreater(sum(tag in n for n in notes), 1)

    def test_a_point_reports_every_measure(self) -> None:
        point = product_bench.measure(60, seed=2, queries=8)
        self.assertEqual(set(point), {"memories", "quality", "latency_ms", "throughput_per_s",
                                      "growth", "false_blocks"})
        self.assertEqual(point["false_blocks"]["benign_writes"], 200)
        self.assertGreater(point["quality"]["recall_at_5"], 0)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
