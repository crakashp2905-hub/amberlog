import unittest
import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
from unittest import mock

from memory_fabric import MemoryFabric
from memory_fabric.docsource import import_document
from memory_fabric.import_preview import plan_batch, apply_batch


def doc(identity="guide", text="Unit P1 limit is 10 bar.", version="1"):
    return {"doc_id": identity, "version": version, "sections": [{"path": "1", "text": text}]}


class ImportPreview(unittest.TestCase):
    def test_cli_batch_preview_and_guarded_commit(self):
        with TemporaryDirectory() as directory:
            database = Path(directory) / "batch.db"
            initial = MemoryFabric(str(database))
            head = initial.log.head_seq
            initial.close()
            source = Path(directory) / "batch.json"
            source.write_text(json.dumps([doc("one"), doc("two")]), encoding="utf-8")
            command = [sys.executable, "-m", "memory_fabric", "--db", str(database),
                       "--json", "import-docs", str(source), "--batch"]
            preview = subprocess.run(command + ["--dry-run"], capture_output=True, text=True)
            self.assertEqual(preview.returncode, 0, preview.stderr)
            plan = json.loads(preview.stdout)
            self.assertEqual(plan["head_seq"], head)
            self.assertEqual(len(plan["documents"]), 2)
            committed = subprocess.run(command + ["--expected-head", str(head), "--expected-plan",
                plan["plan_sha256"]], capture_output=True, text=True)
            self.assertEqual(committed.returncode, 0, committed.stderr)
            self.assertEqual(len(json.loads(committed.stdout)["reports"]), 2)

    def setUp(self):
        self.f = MemoryFabric(":memory:", recognise_copies=False)
        self.addCleanup(self.f.close)

    def test_preview_is_read_only_and_reports_potential_downstream_impact(self):
        initial = import_document(self.f, doc(), activate=True)
        from memory_fabric.actions import ActionGate, ActionPolicy, ToolRule
        gate = ActionGate(self.f, ActionPolicy(tools={"inspect": ToolRule("inspect")},
            grants={"reader": frozenset({"inspect"})}, approvers=frozenset({"reviewer"})))
        self.f.elevate(initial.added[0], approver="reviewer", reason="checked source")
        child = self.f.derive("planner", "Plan inspection at 10 bar.", parents=initial.added, scope="team")
        certificate = self.f.certify("Unit P1 limit is 10 bar.", initial.added, "reader")
        self.assertTrue(gate.authorize("inspect", "reader", certificate).allowed)
        head = self.f.log.head_seq
        plan = plan_batch(self.f, [doc(text="Unit P1 limit is 12 bar.", version="2")])
        self.assertEqual(self.f.log.head_seq, head)
        self.assertEqual(plan.documents[0]["withdrawn_ids"], initial.added)
        self.assertEqual(plan.documents[0]["added_paths"], ["1"])
        self.assertIn(child, plan.potential_dependents)
        self.assertIn(head, plan.potential_action_sequences)

    def test_stale_head_and_changed_input_are_refused_before_writes(self):
        plan = plan_batch(self.f, [doc()])
        with self.assertRaises(ValueError):
            apply_batch(self.f, [doc(text="Unit P1 limit is 12 bar.")], expected_plan=plan.plan_sha256)
        self.f.remember("writer", "An unrelated note.")
        head = self.f.log.head_seq
        with self.assertRaises(ValueError):
            apply_batch(self.f, [doc()], expected_head=plan.head_seq)
        self.assertEqual(self.f.log.head_seq, head)

    def test_partial_batch_failure_rolls_back_log_and_projection_then_retry_is_idempotent(self):
        from memory_fabric import import_preview
        original = import_preview.import_document
        calls = 0

        def fail_second(*args, **kw):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise RuntimeError("injected batch failure")
            return original(*args, **kw)

        before = self.f.log.head_seq
        with mock.patch.object(import_preview, "import_document", side_effect=fail_second):
            with self.assertRaises(RuntimeError):
                apply_batch(self.f, [doc("one"), doc("two")])
        self.assertEqual(self.f.log.head_seq, before)
        self.assertFalse(self.f.state.memories)
        first = apply_batch(self.f, [doc("one"), doc("two")])
        second = apply_batch(self.f, [doc("one"), doc("two")])
        self.assertTrue(all(r.added for r in first))
        self.assertTrue(all(not r.added and r.unchanged for r in second))

    def test_duplicate_doc_ids_and_malformed_batch_fail_before_any_write(self):
        for trees in ([doc(), doc()], [doc(), {"doc_id": "bad"}], []):
            head = self.f.log.head_seq
            with self.assertRaises(ValueError):
                apply_batch(self.f, trees)
            self.assertEqual(self.f.log.head_seq, head)

    def test_other_tenant_does_not_appear_in_default_preview(self):
        imported = import_document(self.f, doc(), tenant_id="other", activate=True)
        plan = plan_batch(self.f, [doc(text="Unit P1 limit is 12 bar.", version="2")])
        self.assertEqual(plan.documents[0]["withdrawn_ids"], [])
        self.assertEqual(plan.potential_dependents, [])
        self.assertNotIn(imported.added[0], str(plan.to_json()))
