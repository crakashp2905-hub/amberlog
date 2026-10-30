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


class ReviewRegressions(unittest.TestCase):
    """Edits that change no section's text withdraw nothing."""

    def setUp(self):
        self.fabric = MemoryFabric(":memory:")
        self.addCleanup(self.fabric.close)

    def reimport(self, old, new):
        first = import_document(self.fabric, compile_doc(old), activate=True)
        child = self.fabric.derive("planner", "Follow the notes.", parents=first.added[:1], scope="team")
        self.fabric.validate(child, actor="reviewer")
        return first, import_document(self.fabric, compile_doc(new, "2"), activate=True), child

    def test_inserting_a_same_named_heading_withdraws_nothing(self):
        first, second, child = self.reimport("# A\n## Notes\nx\n## Notes\ny",
                                             "# A\n## Notes\nnew\n## Notes\nx\n## Notes\ny")
        self.assertEqual(second.withdrawn, [])
        self.assertEqual(sorted(second.unchanged), sorted(first.added))
        self.assertEqual(len(second.added), 1)
        self.assertIs(self.fabric.get(child).lifecycle_state, LifecycleState.ACTIVE)

    def test_moving_a_section_under_a_new_parent_withdraws_nothing(self):
        first, second, child = self.reimport("# Ops\n## Release\nReview it.",
                                             "# Ops\n# Deploy\n## Release\nReview it.")
        self.assertEqual((second.withdrawn, second.added), ([], []))
        self.assertIs(self.fabric.get(child).lifecycle_state, LifecycleState.ACTIVE)
        # A later real edit at the new path still withdraws the old memory.
        third = import_document(self.fabric, compile_doc("# Ops\n# Deploy\n## Release\nSkip it.", "3"))
        self.assertEqual(third.withdrawn, first.added)

    def test_headings_without_text_make_no_section(self):
        tree = compile_doc("# Ops\n## Release\nReview it.\n# Empty\n")
        self.assertEqual([s["title"] for s in tree["sections"]], ["Release"])

    def test_setext_headings(self):
        tree = compile_doc("Guide\n=====\nIntro.\n\nRelease\n-------\nReview it.\n\n- item\n---\n")
        self.assertEqual([s["title"] for s in tree["sections"]], ["Guide", "Release"])
        self.assertEqual(tree["sections"][1]["path"].count("/"), 1)
        self.assertEqual(tree["sections"][1]["line_start"], 5)
        self.assertIn("- item", tree["sections"][1]["text"])
