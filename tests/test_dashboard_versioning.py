"""The dashboard's branch, receipt, correction and capability routes: read-only and checked."""

from __future__ import annotations

import json
import unittest

from amberlog import Amberlog
from amberlog.branching import Branches
from amberlog.context_receipt import build_context
from amberlog.observability.server import Api, ApiError


class Routes(unittest.TestCase):
    def setUp(self) -> None:
        self.f = Amberlog(":memory:", auto_activate=True)
        self.addCleanup(self.f.close)
        self.p1 = self.f.remember("ann", "Pump P1 runs at 4 bar.", scope="team")
        b = Branches(self.f)
        b.create("trial", owner="ann")
        with b.commit("trial", "ann", "re-measure") as c:
            c.revise(self.p1, "Pump P1 runs at 5 bar.")
        self.receipt = build_context(self.f, "ann", "secret words pump p1").receipt
        self.api = Api(self.f)

    def get(self, path: str, **params: str) -> object:
        return self.api.handle(path, {k: [v] for k, v in params.items()})

    def test_branches_list_detail_and_preview(self) -> None:
        self.assertEqual([b["name"] for b in self.get("/api/branches")], ["trial"])
        detail = self.get("/api/branches/trial")
        self.assertEqual(len(detail["history"]), 1)
        preview = self.get("/api/branches/trial/preview")
        self.assertEqual(preview["changes"][0]["decision"], "allow")
        self.assertNotIn("5 bar", json.dumps(detail))

    def test_previewing_writes_nothing(self) -> None:
        head = self.f.log.head_seq
        self.get("/api/branches/trial/preview")
        self.get(f"/api/memories/{self.p1}/correction")
        self.assertEqual(self.f.log.head_seq, head)

    def test_receipts_and_explanation_hold_no_query_or_content(self) -> None:
        rows = self.get("/api/receipts")
        self.assertEqual(len(rows), 1)
        explained = self.get(f"/api/receipts/{self.receipt['receipt_id']}")
        text = json.dumps([rows, explained])
        self.assertNotIn("secret words", text)
        self.assertNotIn("4 bar", text)

    def test_receipts_filter_by_tenant(self) -> None:
        self.assertEqual(self.get("/api/receipts", tenant="tn_other"), [])
        with self.assertRaises(ApiError):
            self.get(f"/api/receipts/{self.receipt['receipt_id']}", tenant="tn_other")

    def test_malformed_ids_are_refused_before_the_store(self) -> None:
        for path in ("/api/branches/Bad Name", "/api/receipts/nope", "/api/memories/x/correction"):
            with self.assertRaises(ApiError):
                self.get(path)
        with self.assertRaises(ApiError):
            self.get("/api/branches/missing")

    def test_correction_preview_carries_its_digest(self) -> None:
        data = self.get(f"/api/memories/{self.p1}/correction")
        self.assertEqual(len(data["digest"]), 64)

    def test_capabilities_are_the_registry(self) -> None:
        data = self.get("/api/capabilities")
        ids = {c["id"]: c["status"] for c in data["capabilities"]}
        self.assertEqual(ids["versioning.branches"], "available")
        self.assertEqual(ids["context.decay"], "experimental")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
