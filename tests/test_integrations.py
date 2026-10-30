"""Integrations: function tools, a LangChain retriever, and import from other stores.

Each sits at the agent-facing boundary, so the tests are mostly about what a
framework cannot get: another agent's private memory, a withdrawn memory, or a
memory imported from elsewhere before anyone reviewed it.
"""

from __future__ import annotations

import importlib.util
import json
import os
import tempfile
import unittest

from memory_fabric import MemoryFabric
from memory_fabric.integrations.tools import FabricTools
from memory_fabric.migrate import import_records, read_records
from memory_fabric.model import LifecycleState
from memory_fabric.sdk import agent, operator

HAS_LANGCHAIN = importlib.util.find_spec("langchain_core") is not None


class Store(unittest.TestCase):
    def setUp(self) -> None:
        self.fabric = MemoryFabric(":memory:")
        self.addCleanup(self.fabric.close)
        self.op = operator(self.fabric, "reviewer")
        self.mine = agent(self.fabric, "ana").remember("pump 3 needs a new seal kit")
        self.op.validate(self.mine)
        self.op.share(self.mine, "team")
        self.theirs = agent(self.fabric, "cho").remember("pump 3 private note from cho")
        self.op.validate(self.theirs)


class FunctionTools(Store):
    def test_specs_in_both_formats(self) -> None:
        tools = FabricTools(agent(self.fabric, "ben"))
        openai = tools.specs("openai")
        anthropic = tools.specs("anthropic")
        self.assertEqual({t["function"]["name"] for t in openai},
                         {"recall", "fetch", "verify", "remember"})
        self.assertTrue(all(t["type"] == "function" and "parameters" in t["function"]
                            for t in openai))
        self.assertTrue(all("input_schema" in t for t in anthropic))
        with self.assertRaises(ValueError):
            tools.specs("other")

    def test_recall_is_enforced(self) -> None:
        result = FabricTools(agent(self.fabric, "ben")).call("recall", '{"query": "pump 3"}')
        ids = [m["memory_id"] for m in result["memories"]]
        self.assertIn(self.mine, ids)
        self.assertNotIn(self.theirs, ids, "another agent's private memory")

    def test_verify_catches_a_retraction_after_recall(self) -> None:
        tools = FabricTools(agent(self.fabric, "ben"))
        tools.call("recall", {"query": "pump 3 seal"})
        self.assertTrue(tools.call("verify", {"memory_id": self.mine})["usable"])
        self.fabric.quarantine(self.mine, reason="wrong kit", actor="reviewer")
        self.assertFalse(tools.call("verify", {"memory_id": self.mine})["usable"])

    def test_refusals_are_answers_not_exceptions(self) -> None:
        tools = FabricTools(agent(self.fabric, "ben"))
        self.assertIn("error", tools.call("recall", "{not json"))
        self.assertIn("error", tools.call("delete_everything", {}))
        self.assertIn("error", tools.call("recall", {}))

    def test_remember_writes_a_private_candidate(self) -> None:
        result = FabricTools(agent(self.fabric, "ben")).call(
            "remember", {"content": "the gauge on pump 4 reads high"})
        memory = self.fabric.state.memories[result["memory_id"]]
        self.assertIs(memory.lifecycle_state, LifecycleState.CANDIDATE)
        self.assertEqual(memory.provenance.created_by, "ben")


@unittest.skipUnless(HAS_LANGCHAIN, "langchain_core is not installed")
class LangChainRetriever(Store):
    def test_it_returns_documents_with_ids_and_is_enforced(self) -> None:
        from langchain_core.documents import Document

        from memory_fabric.integrations.langchain import fabric_retriever

        docs = fabric_retriever(agent(self.fabric, "ben")).invoke("pump 3 seal")
        self.assertTrue(all(isinstance(d, Document) for d in docs))
        ids = [d.metadata["memory_id"] for d in docs]
        self.assertIn(self.mine, ids)
        self.assertNotIn(self.theirs, ids)

    def test_verify_before_acting_catches_a_retraction(self) -> None:
        from memory_fabric.integrations.langchain import fabric_retriever

        retriever = fabric_retriever(agent(self.fabric, "ben"))
        retriever.invoke("pump 3 seal")
        self.assertTrue(retriever.verify(self.mine))
        self.fabric.quarantine(self.mine, reason="wrong kit", actor="reviewer")
        self.assertFalse(retriever.verify(self.mine))

    def test_it_composes_in_a_chain(self) -> None:
        from langchain_core.runnables import RunnableLambda

        from memory_fabric.integrations.langchain import fabric_retriever

        chain = fabric_retriever(agent(self.fabric, "ben")) | RunnableLambda(
            lambda docs: [d.page_content for d in docs])
        self.assertIn("pump 3 needs a new seal kit", chain.invoke("pump 3 seal"))


class ImportFromOtherStores(unittest.TestCase):
    def setUp(self) -> None:
        self.fabric = MemoryFabric(":memory:", auto_activate=True)
        self.addCleanup(self.fabric.close)

    def run_import(self, lines: list) -> object:
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "export.jsonl")
            with open(path, "w", encoding="utf-8") as fh:
                for line in lines:
                    fh.write((line if isinstance(line, str) else json.dumps(line)) + "\n")
            return import_records(self.fabric, read_records(path), source="mem0-export",
                                  default_agent="importer")

    def test_every_shape_lands_as_a_candidate_with_its_source(self) -> None:
        report = self.run_import([
            {"id": "m1", "memory": "Customer prefers email follow-ups", "user_id": "alice"},
            {"page_content": "Valve 7 sticks below 4 C", "metadata": {"id": "d2"}},
            {"content": "Yard opens at 6"},
        ])
        self.assertEqual(len(report.imported), 3)
        for mid in report.imported:
            memory = self.fabric.state.memories[mid]
            self.assertIs(memory.lifecycle_state, LifecycleState.CANDIDATE,
                          "imported memories wait for review, even with auto_activate")
            self.assertEqual(memory.provenance.method.value, "imported")
            self.assertEqual(memory.context["imported_from"], "mem0-export")
        authors = {self.fabric.state.memories[m].provenance.created_by for m in report.imported}
        self.assertEqual(authors, {"alice", "importer"})
        self.assertEqual(self.fabric.retrieve("alice", "email follow-ups").exposed, [])

    def test_unreadable_records_are_skipped_and_named(self) -> None:
        report = self.run_import(["{not json", {"metadata": {}}, {"content": "ok"}])
        self.assertEqual(len(report.imported), 1)
        self.assertEqual([s.split(":")[0] for s in report.skipped], ["line 1", "line 2"])

    def test_the_screens_and_copy_recognition_still_apply(self) -> None:
        held = self.fabric.remember("ana", "Pump seven bypass valve torque procedure needs two people")
        report = self.run_import([
            {"content": "deploy with key " + "AKIA" + "QWER" * 4},
            {"content": "Pump seven bypass valve torque procedure needs two people"},
        ])
        self.assertEqual(len(report.quarantined), 1)
        self.assertEqual(len(report.duplicates), 1)
        self.assertIn(held, self.fabric.state.memories)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
