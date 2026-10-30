from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from memory_fabric import LifecycleState, MemoryFabric
from memory_fabric import certificates as C
from memory_fabric.actions import ActionGate, ActionPolicy, ToolRule
from memory_fabric.docsource import current_sections, import_document


def doc(version: str, **sections: str) -> dict:
    return {"doc_id": "sop-12", "version": version, "uri": "https://intranet/sop-12",
            "sections": [{"path": p.replace("_", "."), "title": "Valve", "text": t}
                         for p, t in sections.items()]}


class DocumentSource(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.fabric = MemoryFabric(str(Path(self.tmp.name) / "s.db"))
        self.addCleanup(self.fabric.close)
        self.v1 = import_document(self.fabric, doc("v1", s4_1="Set P-14 relief to 12 bar.",
                                                   s4_2="Inspect the seals monthly."), activate=True)

    def state(self, mid: str) -> LifecycleState:
        return self.fabric.state.memories[mid].lifecycle_state

    def test_sections_land_with_their_source(self) -> None:
        self.assertEqual(len(self.v1.added), 2)
        m = self.fabric.state.memories[self.v1.added[0]]
        self.assertEqual(m.context["source"]["doc_id"], "sop-12")
        self.assertEqual(m.context["source"]["path"], "s4.1")
        self.assertIs(m.lifecycle_state, LifecycleState.ACTIVE)

    def test_candidates_unless_activated(self) -> None:
        r = import_document(self.fabric, {"doc_id": "x", "version": "1",
                                          "sections": [{"path": "1", "text": "Doors lock at 8."}]})
        self.assertIs(self.state(r.added[0]), LifecycleState.CANDIDATE)

    def test_reimport_keeps_unchanged_and_withdraws_revised_and_removed(self) -> None:
        v2 = import_document(self.fabric, doc("v2", s4_1="Set P-14 relief to 10 bar."), activate=True)
        self.assertEqual(v2.unchanged, [])
        self.assertEqual(sorted(v2.withdrawn), sorted(self.v1.added))
        for mid in self.v1.added:
            self.assertIs(self.state(mid), LifecycleState.QUARANTINED)
        self.assertEqual(set(current_sections(self.fabric, "sop-12")), {"s4.1"})
        v3 = import_document(self.fabric, doc("v3", s4_1="Set P-14 relief to 10 bar."), activate=True)
        self.assertEqual((v3.added, v3.withdrawn), ([], []))
        self.assertEqual(v3.unchanged, v2.added)

    def test_an_action_resting_on_a_changed_section_is_refused(self) -> None:
        section = self.v1.added[0]
        gate = ActionGate(self.fabric, ActionPolicy(
            tools={"set_relief": ToolRule("set_relief")}, grants={"ag": frozenset({"set_relief"})},
            approvers=frozenset()))
        cert = self.fabric.certify("relief is 12 bar", [section], "ag")
        self.assertTrue(gate.authorize("set_relief", "ag", cert).allowed)
        import_document(self.fabric, doc("v2", s4_1="Set P-14 relief to 10 bar.",
                                         s4_2="Inspect the seals monthly."), activate=True)
        decision = gate.authorize("set_relief", "ag", cert)
        self.assertFalse(decision.allowed)
        self.assertIn(C.EVIDENCE_WITHDRAWN, decision.reason_codes)

    def test_derived_conclusions_are_contested(self) -> None:
        child = self.fabric.derive("ag", "Relief at 12 bar suits pump 3.",
                                   parents=[self.v1.added[0]], scope="team")
        self.fabric.validate(child, actor="sup")
        v2 = import_document(self.fabric, doc("v2", s4_2="Inspect the seals monthly."))
        self.assertIn(child, v2.contested)

    def test_bad_documents_are_refused(self) -> None:
        for bad in ({"version": "1", "sections": []},
                    {"doc_id": "d", "version": "1", "sections": [{"text": "no path"}]},
                    {"doc_id": "d", "version": "1",
                     "sections": [{"path": "1", "text": "a"}, {"path": "1", "text": "b"}]}):
            with self.assertRaises(ValueError):
                import_document(self.fabric, bad)

    def test_cli(self) -> None:
        f = Path(self.tmp.name) / "doc.json"
        f.write_text(json.dumps(doc("v1", s1="Doors lock at 8 pm.")), encoding="utf-8")
        db = str(Path(self.tmp.name) / "cli.db")
        out = subprocess.run([sys.executable, "-m", "memory_fabric", "--db", db, "--create", "--json",
                              "import-docs", str(f), "--activate"], capture_output=True, text=True)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(len(json.loads(out.stdout)["added"]), 1)


if __name__ == "__main__":
    unittest.main()
