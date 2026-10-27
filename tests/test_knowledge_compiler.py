"""Compiler structure and governance regressions, without models or network."""
import unittest
import json
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

from memory_fabric import MemoryFabric, LifecycleState
from memory_fabric.docsource import import_document
from memory_fabric.knowledge_compiler import compile_markdown


def compile_doc(text, version="1"):
    return compile_markdown(text, doc_id="handbook", version=version)


class CompilerTests(unittest.TestCase):
    def test_cli_imports_markdown_and_requires_source_identity(self):
        with TemporaryDirectory() as directory:
            source = Path(directory) / "source.md"
            source.write_text("# Release\nReview every release.", encoding="utf-8")
            command = [sys.executable, "-m", "memory_fabric", "--db", ":memory:",
                       "--json", "import-docs", str(source), "--format", "markdown"]
            missing = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(missing.returncode, 4, missing.stderr)
            self.assertIn("--doc-id", missing.stderr)
            imported = subprocess.run(command + ["--doc-id", "release", "--source-version", "1"],
                                      capture_output=True, text=True)
            self.assertEqual(imported.returncode, 0, imported.stderr)
            self.assertEqual(len(json.loads(imported.stdout)["added"]), 1)

    def test_anchors_survive_unrelated_insertion(self):
        old = compile_doc("# Operations\n## Release\nReview before release.")
        new = compile_doc("# Overview\nIntroduction.\n# Operations\n## Release\nReview before release.")
        self.assertEqual(old["sections"][-1]["path"], new["sections"][-1]["path"])

    def test_fences_tables_and_duplicate_headings(self):
        tree = compile_doc("# Notes\n```markdown\n# Literal\n```\n"
                           "| key | value |\n| --- | --- |\n| mode | review |\n"
                           "# Notes\nSecond.\n# Notes-2\nThird.")
        self.assertEqual(len(tree["sections"]), 3)
        self.assertEqual(len({s["path"] for s in tree["sections"]}), 3)
        self.assertIn("# Literal", tree["sections"][0]["text"])
        self.assertIn("| mode | review |", tree["sections"][0]["text"])

    def test_empty_identity_rejected(self):
        with self.assertRaises(ValueError):
            compile_markdown("text", doc_id=" ", version="1")

    def test_compilation_does_not_approve_and_correction_contests_derivative(self):
        fabric = MemoryFabric(":memory:")
        self.addCleanup(fabric.close)
        first = import_document(fabric, compile_doc("# Release\nReview every release."))
        mid = first.added[0]
        self.assertIs(fabric.get(mid).lifecycle_state, LifecycleState.CANDIDATE)
        fabric.validate(mid, actor="reviewer")
        child = fabric.derive("planner", "Plan a release review.", parents=[mid], scope="team")
        fabric.validate(child, actor="reviewer")
        second = import_document(fabric, compile_doc("# Release\nRequire two reviewers.", "2"))
        self.assertIn(mid, second.withdrawn)
        self.assertIn(child, second.contested)
        self.assertIs(fabric.get(second.added[0]).lifecycle_state, LifecycleState.CANDIDATE)

    def test_unchanged_section_does_not_write_another_memory(self):
        fabric = MemoryFabric(":memory:")
        self.addCleanup(fabric.close)
        tree = compile_doc("# Release\nReview every release.")
        first = import_document(fabric, tree)
        second = import_document(fabric, tree)
        self.assertEqual(second.unchanged, first.added)
        self.assertEqual(second.added, [])

    def test_default_import_cannot_withdraw_another_tenants_document(self):
        fabric = MemoryFabric(":memory:")
        self.addCleanup(fabric.close)
        other = import_document(fabric, compile_doc("# Release\nReview every release."),
                                tenant_id="other", activate=True)
        default = import_document(fabric, compile_doc("# Release\nRequire two reviewers.", "2"))
        self.assertEqual(default.withdrawn, [])
        self.assertIs(fabric.get(other.added[0]).lifecycle_state, LifecycleState.ACTIVE)
