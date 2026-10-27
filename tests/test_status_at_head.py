"""The status page and results manifest are generated, current, and free of version contradictions."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import results_manifest  # noqa: E402
import status_at_head  # noqa: E402


class StatusAtHead(unittest.TestCase):
    def test_no_version_contradictions(self) -> None:
        self.assertEqual(status_at_head.contradictions(status_at_head.versions()), [])

    def test_page_is_current(self) -> None:
        self.assertEqual(status_at_head.OUT.read_text(encoding="utf-8"), status_at_head.render(),
                         "regenerate: python tools/status_at_head.py --write")

    def test_manifest_is_current(self) -> None:
        self.assertEqual(results_manifest.OUT.read_text(encoding="utf-8"), results_manifest.render(),
                         "regenerate: python tools/results_manifest.py --write")

    def test_detects_a_drifted_spec(self) -> None:
        v = dict(status_at_head.versions(), spec_header="0.0.1")
        self.assertTrue(status_at_head.contradictions(v))

    def test_manifest_never_invents_a_field(self) -> None:
        for row in results_manifest.build()["rows"]:
            if row["git_sha"] is None:
                self.assertIsNone(row["git_sha_source"])
            self.assertEqual(len(row["file_sha256"]), 64)


if __name__ == "__main__":
    unittest.main()
