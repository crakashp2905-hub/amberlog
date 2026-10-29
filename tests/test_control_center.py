"""The Memory Control Center's read-only API (dashboard), on a sandbox store."""

from __future__ import annotations

import os
import tempfile
import unittest

from amberlog import Amberlog
from amberlog.demo import seed_sandbox
from amberlog.observability.server import Api, ApiError


class ControlCenter(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.tmp = tempfile.TemporaryDirectory()
        cls.f = Amberlog(os.path.join(cls.tmp.name, "s.db"), auto_activate=True)
        cls.seeded = seed_sandbox(cls.f)
        cls.api = Api(cls.f)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.f.close()
        cls.tmp.cleanup()

    def get(self, path: str, **params: str):
        return self.api.handle(path, {k: [v] for k, v in params.items()})

    def test_nothing_here_writes(self) -> None:
        before = sum(1 for _ in self.f.log.read())
        gauge = self.seeded["sandbox_gauge"]
        self.get(f"/api/memories/{gauge}/why", agent="ag_ops", q="valve V-7 pressure")
        self.get(f"/api/memories/{gauge}/dependence")
        for row in self.get("/api/actions"):
            self.get(f"/api/actions/{row['seq']}")
        self.get("/api/limitations")
        self.assertEqual(sum(1 for _ in self.f.log.read()), before)

    def test_why_names_the_first_blocker(self) -> None:
        w = self.get(f"/api/memories/{self.seeded['sandbox_gauge']}/why", q="valve V-7 pressure")
        self.assertFalse(w["eligible"])
        self.assertEqual(w["first_blocker"]["check"], "lifecycle")

    def test_why_ranks_an_eligible_memory(self) -> None:
        w = self.get(f"/api/memories/{self.seeded['sandbox_second']}/why", agent="ag_ops",
                     q="valve V-7 pressure gauge")
        self.assertTrue(w["eligible"], w)
        self.assertIsNotNone(w["rank"])

    def test_actions_show_evidence_changed_since(self) -> None:
        rows = self.get("/api/actions")
        self.assertGreaterEqual(len(rows), 3)
        allowed = [r for r in rows if r["allowed"]]
        details = [self.get(f"/api/actions/{r['seq']}") for r in allowed]
        self.assertTrue(any(d["still_holds"] is False for d in details))
        refused = [r for r in rows if not r["allowed"]]
        self.assertIn("insufficient_independent_support", refused[0]["reason_codes"])

    def test_dependence_separates_depended_from_standing(self) -> None:
        d = self.get(f"/api/memories/{self.seeded['sandbox_gauge']}/dependence")
        self.assertEqual([x["claim_id"] for x in d["depended"]], ["open-valve-7"])
        self.assertEqual([x["claim_id"] for x in d["would_stand"]], ["open-valve-7-checked"])

    def test_limitations_are_served(self) -> None:
        lims = self.get("/api/limitations")
        self.assertTrue(any("offline peer" in x["limitation"].lower() for x in lims))

    def test_bad_action_id_is_refused(self) -> None:
        with self.assertRaises(ApiError):
            self.get("/api/actions/not-a-number")
        with self.assertRaises(ApiError):
            self.get("/api/actions/999999")


class LimitationsInSync(unittest.TestCase):
    def test_the_dashboard_list_matches_the_doc(self) -> None:
        import subprocess
        import sys
        from pathlib import Path

        root = Path(__file__).resolve().parent.parent
        result = subprocess.run([sys.executable, str(root / "tools" / "gen_limitations.py"),
                                 "--check"], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout)


if __name__ == "__main__":
    unittest.main()
