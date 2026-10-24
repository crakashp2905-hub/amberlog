"""ClaudeChat speaks the experiments' chat interface, with no network or key."""

from __future__ import annotations

import unittest
from types import SimpleNamespace

from memory_fabric.adapters.claude_chat import ClaudeChat, make_client
from memory_fabric.adapters.ollama import OllamaClient


class FakeMessages:
    def __init__(self, text: str) -> None:
        self.text, self.calls = text, []

    def create(self, **kwargs: object) -> object:
        self.calls.append(kwargs)
        return SimpleNamespace(content=[SimpleNamespace(text=self.text)], stop_reason="end_turn",
                               usage=SimpleNamespace(input_tokens=12, output_tokens=5))


class Chat(unittest.TestCase):
    def test_reply_shape_system_prompt_and_call_record(self) -> None:
        fake = FakeMessages("Answer: 42")
        client = ClaudeChat(SimpleNamespace(messages=fake))
        reply = client.chat("claude-sonnet-5-5", [{"role": "system", "content": "Be brief."},
                                                  {"role": "user", "content": "6 x 7?"}])
        self.assertEqual(reply["message"]["content"], "Answer: 42")
        sent = fake.calls[0]
        self.assertEqual(sent["system"], "Be brief.")
        self.assertEqual(sent["messages"], [{"role": "user", "content": "6 x 7?"}])
        record = client.calls[0]
        self.assertEqual((record.prompt_tokens, record.completion_tokens), (12, 5))
        self.assertEqual(len(record.prompt_sha256), 64)

    def test_a_schema_reply_is_reduced_to_its_json_object(self) -> None:
        client = ClaudeChat(SimpleNamespace(messages=FakeMessages(
            'Here you go: {"injection": true, "reason": "override"} done')))
        reply = client.chat("claude-sonnet-5-5", [{"role": "user", "content": "x"}],
                            schema={"type": "object"})
        self.assertEqual(reply["message"]["content"], '{"injection": true, "reason": "override"}')

    def test_make_client_picks_by_model_id(self) -> None:
        self.assertIsInstance(make_client("qwen2.5:3b"), OllamaClient)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
