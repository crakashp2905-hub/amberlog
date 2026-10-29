"""Bring-your-own model: parsing, each provider's wire format, logging, no secrets."""

from __future__ import annotations

import io
import json
import os
import types
import unittest
from unittest import mock

from amberlog.models import CallLog, ModelClient, ModelError, ModelSpec, configured


def fake_http(seen):
    def opener(request, timeout):
        seen["url"] = request.full_url
        seen["headers"] = {k.lower(): v for k, v in request.header_items()}
        seen["body"] = json.loads(request.data)
        return io.BytesIO(json.dumps({"choices": [{"message": {"content": "hello"}}],
                                      "usage": {"prompt_tokens": 7, "completion_tokens": 2}}
                                     ).encode())
    return opener


class TestSpec(unittest.TestCase):
    def test_parse(self):
        self.assertEqual(ModelSpec.parse("anthropic:claude-opus-5-5"),
                         ModelSpec("anthropic", "claude-opus-5-5"))
        self.assertEqual(ModelSpec.parse("ollama:qwen2.5:7b").model, "qwen2.5:7b")
        s = ModelSpec.parse("compat:my-model@https://llm.internal/v1")
        self.assertEqual((s.model, s.base_url), ("my-model", "https://llm.internal/v1"))
        for bad in ("gpt-4", "nope:x", "compat:x", "openai:"):
            with self.assertRaises(ValueError):
                ModelSpec.parse(bad)

    def test_no_model_chosen_is_an_error_not_a_default(self):
        with mock.patch.dict(os.environ, {}, clear=True), self.assertRaises(ModelError):
            ModelClient()
        with mock.patch.dict(os.environ, {"AMBERLOG_MODEL": "ollama:llama3"}):
            self.assertEqual(str(ModelClient().spec), "ollama:llama3")


class TestProviders(unittest.TestCase):
    def test_openai_compatible_wire_format_and_key(self):
        seen = {}
        with mock.patch.dict(os.environ, {"OPENAI_API_KEY": "k-1"}):
            c = ModelClient("openai:gpt-test", opener=fake_http(seen),
                            prices={"gpt-test": (1.0, 2.0)})
            r = c.complete("hi", system="be brief", max_tokens=5)
        self.assertEqual(seen["url"], "https://api.openai.com/v1/chat/completions")
        self.assertEqual(seen["headers"]["authorization"], "Bearer k-1")
        self.assertEqual(seen["body"]["messages"][0], {"role": "system", "content": "be brief"})
        self.assertEqual((r.text, r.input_tokens, r.output_tokens), ("hello", 7, 2))
        self.assertAlmostEqual(r.cost_usd, 7e-6 + 4e-6)

    def test_local_providers_need_no_key(self):
        seen = {}
        with mock.patch.dict(os.environ, {}, clear=True):
            ModelClient("ollama:qwen", opener=fake_http(seen)).complete("x")
        self.assertTrue(seen["url"].startswith("http://127.0.0.1:11434/v1"))
        self.assertNotIn("authorization", seen["headers"])

    def test_missing_key_fails_before_any_request(self):
        with mock.patch.dict(os.environ, {}, clear=True), self.assertRaises(ModelError):
            ModelClient("groq:llama", opener=lambda *a, **k: 1 / 0).complete("x")

    def test_azure_deployment_url_and_header(self):
        seen = {}
        env = {"MF_AZURE_ENDPOINT": "https://r.openai.azure.com", "AZURE_OPENAI_API_KEY": "az"}
        with mock.patch.dict(os.environ, env, clear=True):
            ModelClient("azure:dep1", opener=fake_http(seen)).complete("x")
        self.assertIn("/openai/deployments/dep1/chat/completions?api-version=", seen["url"])
        self.assertEqual(seen["headers"]["api-key"], "az")
        self.assertNotIn("model", seen["body"])

    def test_anthropic_through_the_sdk_shape(self):
        msg = types.SimpleNamespace(
            content=[types.SimpleNamespace(type="text", text="yes")], stop_reason="end_turn",
            usage=types.SimpleNamespace(input_tokens=3, output_tokens=1))
        sdk = mock.Mock()
        sdk.messages.create.return_value = msg
        r = ModelClient("anthropic:claude-opus-5-5", anthropic_client=sdk).complete(
            "q", system="s")
        kwargs = sdk.messages.create.call_args.kwargs
        self.assertEqual(kwargs["model"], "claude-opus-5-5")
        self.assertEqual(kwargs["system"], "s")
        self.assertEqual((r.text, r.input_tokens), ("yes", 3))
        sdk.messages.create.return_value = types.SimpleNamespace(
            content=[], stop_reason="refusal", usage=None)
        with self.assertRaises(ModelError):
            ModelClient("anthropic:claude-opus-5-5", anthropic_client=sdk).complete("q")

    def test_claude_cli_reports_its_own_cost(self):
        def runner(cmd, **kw):
            self.assertIn("--model", cmd)
            return types.SimpleNamespace(stdout=json.dumps({
                "result": "OK", "total_cost_usd": 0.001,
                "usage": {"input_tokens": 2, "output_tokens": 1}}))
        r = ModelClient("claude-cli:haiku", runner=runner).complete("x")
        self.assertEqual((r.text, r.cost_usd), ("OK", 0.001))


class TestLogging(unittest.TestCase):
    def test_log_has_hash_and_tokens_never_prompt_or_key(self):
        import tempfile

        seen = {}
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "calls.jsonl")
            with mock.patch.dict(os.environ, {"OPENAI_API_KEY": "sk-secret-value"}):
                c = ModelClient("openai:m", opener=fake_http(seen), log=CallLog(path))
                c.complete("my private prompt")
            text = open(path).read()
        self.assertNotIn("my private prompt", text)
        self.assertNotIn("sk-secret-value", text)
        row = json.loads(text)
        self.assertEqual(len(row["prompt_hash"]), 64)
        self.assertEqual(c.log.totals()["cost_unknown_calls"], 1)

    def test_configured_lists_every_provider(self):
        self.assertEqual(len(configured()), len({r["provider"] for r in configured()}))


if __name__ == "__main__":
    unittest.main()
