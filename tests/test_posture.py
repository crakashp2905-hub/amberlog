"""Posture reads the store; the audit export never carries content."""

from __future__ import annotations

import json
import os
import tempfile
import unittest

from memory_fabric import MemoryFabric
from memory_fabric.integrity import Checkpoint
from memory_fabric.posture import ACCEPTED_GAPS, export_audit, posture

DISTINCTIVE = "the vendor's 2024 pricing page listed tier 3 at $400 per month"


class Posture(unittest.TestCase):
    def test_controls_follow_the_store_settings(self) -> None:
        reviewed = MemoryFabric(":memory:")
        auto = MemoryFabric(":memory:", auto_activate=True, conceal_cross_tenant=True)
        self.addCleanup(reviewed.close)
        self.addCleanup(auto.close)
        state = lambda f, name: next(c["state"] for c in posture(f)["controls"] if c["name"] == name)
        self.assertEqual(state(reviewed, "new memories wait for review"), "on")
        self.assertEqual(state(auto, "new memories wait for review"), "off")
        self.assertEqual(state(reviewed, "cross-tenant refusals conceal existence"), "off")
        self.assertEqual(state(auto, "cross-tenant refusals conceal existence"), "on")
        # Postgres triggers refuse edits; SQLite cannot. The tests run on
        # either backend (MF_TEST_POSTGRES_URL), and so must the expectation.
        on_postgres = bool(os.environ.get("MF_TEST_POSTGRES_URL"))
        self.assertEqual(state(reviewed, "append-only event log enforced by the database"),
                         "on" if on_postgres else "partial")

    def test_the_accepted_gaps_are_the_reviews(self) -> None:
        here = os.path.dirname(os.path.abspath(__file__))
        review = open(os.path.join(here, "..", "docs", "SECURITY_REVIEW.md"), encoding="utf-8").read()
        for gap_id, _, _ in ACCEPTED_GAPS:
            self.assertIn(f"| {gap_id} |", review, f"{gap_id} is not in the security review")


class AuditExport(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.fabric = MemoryFabric(":memory:", auto_activate=True)
        self.addCleanup(self.fabric.close)
        self.mid = self.fabric.remember("ana", DISTINCTIVE)
        self.fabric.revise(self.mid, DISTINCTIVE + " and tier 4 at $900", agent_id="ana",
                           reason="update")
        self.fabric.retrieve("ana", "vendor pricing tier")
        self.fabric.use(self.mid, "ben")
        self.planted_key = "AKIA" + "ZXCV" * 4
        self.fabric.remember("ana", f"deploy key {self.planted_key}")
        self.fabric.erase_content(self.mid, reason="request", actor="dpo")
        self.path = os.path.join(self.tmp.name, "audit.jsonl")

    def lines(self) -> list[dict]:
        with open(self.path, encoding="utf-8") as fh:
            return [json.loads(line) for line in fh]

    def test_no_content_and_no_secret_leaves(self) -> None:
        export_audit(self.fabric, self.path)
        text = open(self.path, encoding="utf-8").read()
        self.assertNotIn("pricing page", text)
        self.assertNotIn("tier 4", text)
        self.assertNotIn(self.planted_key, text)

    def test_every_kind_is_there_with_actors(self) -> None:
        manifest = export_audit(self.fabric, self.path)
        rows = self.lines()
        self.assertEqual(rows[0]["export"], "memory_fabric audit")
        self.assertEqual(set(manifest["counts"]), {"decisions", "changes", "access", "deletions"})
        erased = [r for r in rows[1:-1] if r.get("type") == "ContentErased"]
        self.assertEqual(erased[0]["actor"], "dpo")
        created = next(r for r in rows[1:-1] if r.get("type") == "MemoryCreated")
        self.assertEqual(created["payload"]["memory"]["created_by"], "ana")

    def test_it_ends_with_a_checkpoint_the_log_agrees_with(self) -> None:
        export_audit(self.fabric, self.path)
        checkpoint = Checkpoint.from_json(self.lines()[-1]["checkpoint"])
        self.assertTrue(self.fabric.log.chain.verify_against(checkpoint).ok)

    def test_kinds_and_since_narrow_it(self) -> None:
        manifest = export_audit(self.fabric, self.path, kinds=["deletions"])
        self.assertEqual(manifest["counts"], {"deletions": 1})
        head = self.fabric.log.head_seq
        self.assertEqual(export_audit(self.fabric, self.path, since_seq=head)["events"], 0)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
