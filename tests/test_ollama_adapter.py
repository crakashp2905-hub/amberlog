"""The Ollama adapter, driven by a stub client.

The live behaviour is exercised by `experiments/live_ollama.py` and
`examples/live_memory_os.py`, which need a running server. These cover the
wiring — tool handling, caching, governance on the write path — without one, so
the suite stays runnable on a machine with no models installed.
"""

from __future__ import annotations

import unittest
from typing import Any, Mapping, Sequence

from memory_fabric import LifecycleState, MemoryFabric, MemoryType
from memory_fabric.adapters.context import OPEN
from memory_fabric.adapters.ollama import (
    REMEMBER_TOOL,
    OllamaEmbedder,
    OllamaMemoryAgent,
)


class StubClient:
    """Records requests and replays scripted replies."""

    def __init__(self, replies: Sequence[Mapping[str, Any]] | None = None) -> None:
        self.replies = list(replies or [])
        self.calls: list[dict[str, Any]] = []
        self.embed_calls: list[list[str]] = []

    def chat(self, model, messages, tools=None, temperature=0.0, num_predict=256):
        self.calls.append(
            {"model": model, "messages": list(messages), "tools": tools,
             "temperature": temperature}
        )
        if self.replies:
            return self.replies.pop(0)
        return {"message": {"role": "assistant", "content": "done"}}

    def embed(self, model, inputs):
        self.embed_calls.append(list(inputs))
        # Distinct but deterministic vectors, so cosine ordering is stable.
        return [[float(len(t)), float(sum(map(ord, t)) % 97), 1.0] for t in inputs]


def text_reply(content: str) -> dict[str, Any]:
    return {"message": {"role": "assistant", "content": content}}


def tool_reply(content: str, kind: str = "semantic") -> dict[str, Any]:
    return {
        "message": {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {"function": {"name": "remember",
                              "arguments": {"content": content, "type": kind}}}
            ],
        }
    }


class TestEmbedder(unittest.TestCase):
    def test_caches_repeated_text(self) -> None:
        """An embed call costs about a second; re-embedding every add and every
        search would dominate any run."""
        client = StubClient()
        embedder = OllamaEmbedder(client)
        first = embedder.embed("a memory")
        second = embedder.embed("a memory")
        self.assertEqual(first, second)
        self.assertEqual(embedder.calls, 1)

    def test_warm_batches_into_one_request(self) -> None:
        client = StubClient()
        embedder = OllamaEmbedder(client)
        embedder.warm([f"memory {i}" for i in range(20)])
        self.assertEqual(len(client.embed_calls), 1)
        self.assertEqual(len(client.embed_calls[0]), 20)
        embedder.embed("memory 5")
        self.assertEqual(embedder.calls, 1)  # served from cache

    def test_warm_skips_what_it_already_has(self) -> None:
        client = StubClient()
        embedder = OllamaEmbedder(client)
        embedder.warm(["a", "b"])
        embedder.warm(["a", "b"])
        self.assertEqual(len(client.embed_calls), 1)

    def test_dimension_follows_the_model(self) -> None:
        embedder = OllamaEmbedder(StubClient())
        embedder.embed("x")
        self.assertEqual(embedder.dim, 3)

    def test_plugs_into_the_fabric(self) -> None:
        fabric = MemoryFabric(auto_activate=True, embedder=OllamaEmbedder(StubClient()))
        try:
            mid = fabric.remember("a", "Use ripgrep for large trees.")
            found = fabric.retrieve("a", "Use ripgrep for large trees.", k=1)
            self.assertEqual([m.id for m in found.exposed], [mid])
        finally:
            fabric.close()


class TestAgent(unittest.TestCase):
    def setUp(self) -> None:
        self.fabric = MemoryFabric(auto_activate=True, seed=1,
                                   embedder=OllamaEmbedder(StubClient()))

    def tearDown(self) -> None:
        self.fabric.close()

    def agent(self, replies, **kwargs) -> OllamaMemoryAgent:
        self.client = StubClient(replies)
        return OllamaMemoryAgent(self.fabric, "agent-a", client=self.client, **kwargs)

    def test_simple_run(self) -> None:
        agent = self.agent([text_reply("use ripgrep")])
        run = agent.run("t1", "how do I search?")
        self.assertEqual(run.text, "use ripgrep")
        self.assertEqual(run.turns, 1)

    def test_memories_are_injected_into_the_user_turn(self) -> None:
        mid = self.fabric.remember("agent-z", "Use ripgrep to search large repositories.")
        agent = self.agent([text_reply("ok")])
        run = agent.run("t1", "Use ripgrep to search large repositories.")
        self.assertIn(mid, run.recalled)
        user = self.client.calls[0]["messages"][-1]["content"]
        self.assertIn(OPEN, user)
        self.assertIn("ripgrep", user)
        # The system prompt stays stable; memories are volatile.
        self.assertNotIn("ripgrep", self.client.calls[0]["messages"][0]["content"])

    def test_recall_can_be_skipped(self) -> None:
        self.fabric.remember("agent-z", "Something retrievable.")
        agent = self.agent([text_reply("ok")])
        run = agent.run("t1", "Something retrievable.", recall=False)
        self.assertEqual(run.recalled, [])
        self.assertNotIn(OPEN, self.client.calls[0]["messages"][-1]["content"])

    def test_tool_is_offered_only_when_enabled(self) -> None:
        agent = self.agent([text_reply("ok")], allow_remember=False)
        agent.run("t1", "hello")
        self.assertIsNone(self.client.calls[0]["tools"])

        agent = self.agent([text_reply("ok")], allow_remember=True)
        agent.run("t2", "hello")
        self.assertEqual(self.client.calls[0]["tools"], [REMEMBER_TOOL])

    def test_remember_tool_writes_an_unvalidated_memory(self) -> None:
        fabric = MemoryFabric(seed=1, embedder=OllamaEmbedder(StubClient()))
        try:
            client = StubClient([tool_reply("Retry a failed deploy once.", "procedural"),
                                 text_reply("noted")])
            agent = OllamaMemoryAgent(fabric, "agent-a", client=client, allow_remember=True)
            run = agent.run("t1", "what did we learn?", recall=False)
            self.assertEqual(len(run.remembered), 1)
            memory = fabric.get(run.remembered[0])
            self.assertIs(memory.lifecycle_state, LifecycleState.CANDIDATE)
            self.assertIs(memory.type, MemoryType.PROCEDURAL)
            self.assertEqual(memory.provenance.created_by, "agent-a")
        finally:
            fabric.close()

    def test_string_arguments_are_parsed(self) -> None:
        """Some models return the arguments object as a JSON string."""
        reply = {
            "message": {
                "role": "assistant", "content": "",
                "tool_calls": [{"function": {
                    "name": "remember",
                    "arguments": '{"content": "A durable fact.", "type": "semantic"}',
                }}],
            }
        }
        agent = self.agent([reply, text_reply("ok")], allow_remember=True)
        run = agent.run("t1", "learn something", recall=False)
        self.assertEqual(len(run.remembered), 1)
        self.assertEqual(self.fabric.get(run.remembered[0]).content, "A durable fact.")

    def test_a_secret_write_is_quarantined_and_reported_back(self) -> None:
        agent = self.agent(
            [tool_reply("the key is AKIAIOSFODNN7EXAMPLE"), text_reply("understood")],
            allow_remember=True,
        )
        run = agent.run("t1", "record the key", recall=False)
        self.assertIs(
            self.fabric.get(run.remembered[0]).lifecycle_state,
            LifecycleState.QUARANTINED,
        )
        tool_turn = next(m for m in self.client.calls[1]["messages"] if m.get("role") == "tool")
        self.assertIn("quarantined", tool_turn["content"])

    def test_empty_tool_content_is_refused_without_crashing(self) -> None:
        agent = self.agent([tool_reply(""), text_reply("ok")], allow_remember=True)
        run = agent.run("t1", "go", recall=False)
        self.assertEqual(run.remembered, [])
        tool_turn = next(m for m in self.client.calls[1]["messages"] if m.get("role") == "tool")
        self.assertIn("non-empty", tool_turn["content"])

    def test_unknown_tool_is_reported(self) -> None:
        reply = {"message": {"role": "assistant", "content": "",
                             "tool_calls": [{"function": {"name": "launch", "arguments": {}}}]}}
        agent = self.agent([reply, text_reply("ok")], allow_remember=True)
        agent.run("t1", "go", recall=False)
        tool_turn = next(m for m in self.client.calls[1]["messages"] if m.get("role") == "tool")
        self.assertIn("unknown tool", tool_turn["content"])

    def test_runaway_tool_loops_are_bounded(self) -> None:
        agent = self.agent([tool_reply(f"fact {i}") for i in range(10)],
                           allow_remember=True, max_turns=3)
        run = agent.run("t1", "loop", recall=False)
        self.assertEqual(run.turns, 3)

    def test_run_records_no_outcome(self) -> None:
        """Outcomes need a verifier other than the agent."""
        agent = self.agent([text_reply("ok")])
        run = agent.run("t1", "hello")
        self.assertIsNone(self.fabric.state.episodes[run.episode_id].outcome)


if __name__ == "__main__":
    unittest.main()
