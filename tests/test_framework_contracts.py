"""Real framework runtimes with deterministic tools; no hosted model or pilot claim."""
from __future__ import annotations

import importlib.util
import json
import unittest
from typing import TypedDict
from unittest.mock import patch

from memory_fabric import MemoryFabric
from memory_fabric.integrations.tools import FabricTools
from memory_fabric.sdk import agent


class WorkflowState(TypedDict, total=False):
    correct: bool
    ids: list[str]
    ran: bool


@unittest.skipUnless(importlib.util.find_spec("langgraph"), "run framework-contracts CI")
class LangGraphContract(unittest.TestCase):
    def test_real_graph_rechecks_evidence_after_correction(self):
        from langgraph.graph import END, START, StateGraph

        from memory_fabric.integrations.langchain import fabric_retriever

        for correct in (False, True):
            with self.subTest(correct=correct), MemoryFabric(":memory:") as store:
                evidence = store.remember("observer", "Valve dispatch requires a reviewed seal.",
                                          scope="team", tenant_id="tn_work", auto_activate=True)
                foreign = store.remember("observer", "Valve FOREIGN_PRIVATE_MARKER seal.",
                                         scope="team", tenant_id="tn_other", auto_activate=True)
                retriever = fabric_retriever(agent(store, "worker", tenant_id="tn_work"))
                effects = []

                def recall(state):
                    docs = retriever.invoke("valve dispatch reviewed seal")
                    self.assertNotIn("FOREIGN_PRIVATE_MARKER", str(docs))
                    return {"ids": [doc.metadata["memory_id"] for doc in docs]}

                def correction(state):
                    if state["correct"]:
                        store.quarantine(evidence, actor="reviewer", reason="source corrected")
                    return {}

                def action(state):
                    # A workflow edge is not authorization: verify after the correction node.
                    usable = evidence in state["ids"] and retriever.verify(evidence)
                    if usable:
                        effects.append("dispatch")
                    return {"ran": usable}

                graph = StateGraph(WorkflowState)
                for name, node in (("recall", recall), ("correction", correction), ("action", action)):
                    graph.add_node(name, node)
                for left, right in ((START, "recall"), ("recall", "correction"),
                                    ("correction", "action"), ("action", END)):
                    graph.add_edge(left, right)
                result = graph.compile().invoke({"correct": correct})
                self.assertIn(evidence, result["ids"], "positive retrieval control")
                self.assertNotIn(foreign, result["ids"])
                self.assertEqual(result["ran"], not correct)
                self.assertEqual(effects, [] if correct else ["dispatch"])


@unittest.skipUnless(importlib.util.find_spec("agents"), "run framework-contracts CI")
class OpenAIAgentsContract(unittest.IsolatedAsyncioTestCase):
    async def test_runner_dispatches_governed_tools_without_hosted_model_calls(self):
        from agents import Agent, FunctionTool, Model, RunConfig, Runner
        from agents.items import ModelResponse
        from agents.usage import Usage
        from openai.types.responses import ResponseFunctionToolCall

        class ToolRequestModel(Model):
            def __init__(self, name, arguments):
                self.name, self.arguments, self.calls = name, arguments, 0

            async def get_response(self, *args, **kwargs):
                self.calls += 1
                return ModelResponse(output=[ResponseFunctionToolCall(
                    id="fc_contract", call_id="call_contract", type="function_call",
                    name=self.name, arguments=json.dumps(self.arguments))],
                    usage=Usage(), response_id="local_contract")

            async def stream_response(self, *args, **kwargs):
                raise AssertionError("this contract uses non-streaming Runner.run")
                yield  # pragma: no cover

        with MemoryFabric(":memory:") as store:
            evidence = store.remember("observer", "Valve dispatch requires a reviewed seal.",
                                      scope="team", tenant_id="tn_work", auto_activate=True)
            foreign = store.remember("observer", "FOREIGN_PRIVATE_MARKER", scope="team",
                                     tenant_id="tn_other", auto_activate=True)
            governed = FabricTools(agent(store, "worker", tenant_id="tn_work"))
            sdk_tools = []
            for spec in governed.specs("openai"):
                definition = spec["function"]

                def bind(name):
                    async def invoke(context, arguments):
                        return json.dumps(governed.call(name, arguments))
                    return invoke

                sdk_tools.append(FunctionTool(
                    name=definition["name"], description=definition["description"],
                    params_json_schema=definition["parameters"], strict_json_schema=False,
                    on_invoke_tool=bind(definition["name"])))

            async def run(name, memory_id):
                model = ToolRequestModel(name, {"memory_id": memory_id})
                worker = Agent(name="governed-worker", model=model, tools=sdk_tools,
                               tool_use_behavior="stop_on_first_tool")
                with patch("httpx.AsyncClient.send", side_effect=AssertionError("network forbidden")), \
                     patch("httpx.Client.send", side_effect=AssertionError("network forbidden")):
                    result = await Runner.run(worker, "Run the requested memory check.",
                                              run_config=RunConfig(tracing_disabled=True), max_turns=2)
                self.assertEqual(model.calls, 1, "the real Runner must call the scripted model")
                return json.loads(result.final_output)

            self.assertIn("reviewed seal", json.dumps(await run("fetch", evidence)))
            hidden = await run("fetch", foreign)
            self.assertIn("error", hidden)
            self.assertNotIn("FOREIGN_PRIVATE_MARKER", json.dumps(hidden))
            self.assertTrue((await run("verify", evidence))["usable"])
            store.quarantine(evidence, actor="reviewer", reason="source corrected")
            self.assertFalse((await run("verify", evidence))["usable"])
            self.assertIn("error", await run("fetch", evidence))
