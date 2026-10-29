"""The Claude adapter against the real `anthropic` SDK, with HTTP stubbed.

The live API is not reachable from every machine that runs this suite (it
needs credentials), so the adapter's loop was only ever tested against a
hand-written stub client (`tests/test_adapters.py`). A stub accepts whatever
the adapter sends. This test instead runs the adapter through the **real SDK**
and intercepts only the HTTP transport. That checks three things a stub cannot:

- the SDK accepts every argument the adapter passes (`fallbacks`, `betas`,
  `output_config`, `strict` tools) and serialises it as the API expects;
- the adapter reads the SDK's own response types, including a `tool_use`
  turn, appends them back append-only, and records the `remember` call;
- the request carries nothing the current model rejects: no `temperature`,
  no `budget_tokens`, no forced `tool_choice`, no assistant prefill.

Skipped when `anthropic` is not installed (CI installs nothing). Run with the
SDK present: `pip install anthropic && python -m unittest tests.test_claude_contract`.
This is a contract test, **not** a live validation, and is recorded as such.
"""

from __future__ import annotations

import json
import unittest

try:
    import anthropic
    import httpx2
except ImportError:  # pragma: no cover - depends on the environment
    anthropic = None

from amberlog import Amberlog
from amberlog.adapters.claude import DEFAULT_MODEL, FALLBACK_BETA, ClaudeMemoryAgent


# Placeholder: the transport is stubbed, so no request leaves the process.
STUB_KEY = "stub"


def _message(content: list[dict], stop: str, msg_id: str) -> dict:
    return {"id": msg_id, "type": "message", "role": "assistant", "model": DEFAULT_MODEL,
            "content": content, "stop_reason": stop, "stop_sequence": None,
            "usage": {"input_tokens": 120, "output_tokens": 30,
                      "cache_read_input_tokens": 80, "cache_creation_input_tokens": 0}}


@unittest.skipIf(anthropic is None, "the anthropic SDK is not installed")
class TestAgainstTheRealSdk(unittest.TestCase):
    def setUp(self) -> None:
        self.requests: list[dict] = []
        self.headers: list[dict] = []
        replies = [
            _message([{"type": "thinking", "thinking": "", "signature": "sig-1"},
                      {"type": "tool_use", "id": "toolu_1", "name": "remember",
                       "input": {"content": "Pilot cable faults show as E01 at coastal sites.",
                                 "type": "semantic"}}], "tool_use", "msg_1"),
            _message([{"type": "text", "text": "Swap the pilot cable."}], "end_turn", "msg_2"),
        ]

        def handler(request: "httpx2.Request") -> "httpx2.Response":
            self.requests.append(json.loads(request.content))
            self.headers.append(dict(request.headers))
            return httpx2.Response(200, json=replies[len(self.requests) - 1])

        client = anthropic.Anthropic(
            api_key=STUB_KEY, base_url="http://stub.invalid", max_retries=0,
            http_client=anthropic.DefaultHttpxClient(transport=httpx2.MockTransport(handler)))
        # A default store: writes land as candidates unless an operator turns
        # auto-activation on. The seed is validated by hand, as a reviewer would.
        # It is written at `team` scope: since scope is enforced on reads (F10),
        # a private memory is visible only to the agent that wrote it, and this
        # seed stands for knowledge the team shares. Seeded private, it is
        # correctly invisible to `ag_claude`, which is how this test failed in
        # CI while skipping locally (no SDK) -- tests/test_adapters.py now
        # covers that recall path without the SDK.
        self.fabric = Amberlog()
        self.addCleanup(self.fabric.close)
        seed = self.fabric.remember("ag_seed", "E01 at coastal sites: swap the pilot cable.",
                                    scope="team")
        self.fabric.validate(seed, actor="reviewer")
        self.seed = seed
        self.agent = ClaudeMemoryAgent(self.fabric, "ag_claude", client=client)
        self.run_result = self.agent.run("t1", "Fault E01 at a coastal site. What do I do?")

    def test_the_loop_completes_through_the_sdk(self) -> None:
        self.assertEqual(self.run_result.text, "Swap the pilot cable.")
        self.assertEqual(self.run_result.turns, 2)
        self.assertEqual(self.run_result.stop_reason, "end_turn")
        self.assertEqual(self.run_result.cache_read_tokens, 160)

    def test_the_remember_call_is_recorded_as_a_candidate(self) -> None:
        self.assertEqual(len(self.run_result.remembered), 1)
        self.assertEqual(self.fabric.lifecycle_of(self.run_result.remembered[0]).value,
                         "candidate")

    def test_recalled_memory_goes_in_the_user_turn_not_the_cached_system(self) -> None:
        first = self.requests[0]
        self.assertIn(self.seed, self.run_result.recalled)
        self.assertIn("pilot cable", json.dumps(first["messages"][0]))
        self.assertNotIn("pilot cable", json.dumps(first["system"]))
        self.assertEqual(first["system"][-1]["cache_control"], {"type": "ephemeral"})

    def test_the_request_uses_only_what_the_current_model_accepts(self) -> None:
        for body in self.requests:
            self.assertEqual(body["model"], "claude-opus-5-5")
            self.assertEqual(body["thinking"], {"type": "adaptive"})
            self.assertIn(body["output_config"]["effort"], {"low", "medium", "high", "xhigh", "max"})
            self.assertEqual(body["fallbacks"], "default")
            for forbidden in ("temperature", "top_p", "top_k", "tool_choice"):
                self.assertNotIn(forbidden, body)
            self.assertNotIn("budget_tokens", json.dumps(body["thinking"]))
            self.assertEqual(body["messages"][-1]["role"], "user", "no assistant prefill")
            tool = body["tools"][0]
            self.assertTrue(tool["strict"])
            self.assertFalse(tool["input_schema"]["additionalProperties"])
        for headers in self.headers:
            self.assertIn(FALLBACK_BETA, headers.get("anthropic-beta", ""))

    def test_history_is_appended_unchanged_including_thinking(self) -> None:
        """Preserved thinking: the second request replays the first reply as is."""
        second = self.requests[1]["messages"]
        self.assertEqual([m["role"] for m in second], ["user", "assistant", "user"])
        replayed = second[1]["content"]
        self.assertEqual(replayed[0], {"type": "thinking", "thinking": "", "signature": "sig-1"})
        self.assertEqual(replayed[1]["id"], "toolu_1")
        results = second[2]["content"]
        self.assertEqual([r["type"] for r in results], ["tool_result"])
        self.assertEqual(results[0]["tool_use_id"], "toolu_1")


if __name__ == "__main__":
    unittest.main()
