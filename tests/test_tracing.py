"""Model-call tracing: the sinks, and the content boundary they defend.

`CallRecord` stores a hash of the prompt rather than the prompt, because a
prompt here contains memory content and may contain exactly what the governance
layer exists to keep out of secondary surfaces. A trace exporter **is** a
secondary surface, so the tests that matter most here are not about the happy
path. They are:

* content is withheld unless asked for, on both sinks;
* a hosted Langfuse plus content is refused rather than warned about;
* a sink that raises cannot fail the model call it is observing.

The last one is the reason sinks exist at all rather than tracing being wired
into `chat` directly: the ledger in `client.calls` is what AGENTS.md requires,
and an exporter is a convenience that must not be able to break it.
"""

from __future__ import annotations

import json
import pathlib
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from memory_fabric.adapters.ollama import CallRecord, OllamaClient  # noqa: E402
from memory_fabric.adapters.tracing import JsonlSink, _is_local  # noqa: E402

RECORD = CallRecord(
    model="qwen2.5:1.5b",
    prompt_sha256="a" * 64,
    prompt_tokens=126,
    completion_tokens=45,
    seconds=2.5,
    constrained=True,
)
MESSAGES = [{"role": "user", "content": "At depot-12, add 0.35 bar."}]
REPLY = {"message": {"content": '{"asserts": false}'}}


def rows(path: pathlib.Path) -> list[dict]:
    return [json.loads(line) for line in
            path.read_text(encoding="utf-8").splitlines() if line.strip()]


class TestJsonlSink(unittest.TestCase):
    def test_metadata_is_written_and_content_is_not(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "t.jsonl"
            JsonlSink(path)(RECORD, "qwen2.5:1.5b", MESSAGES, REPLY)
            row = rows(path)[0]
            self.assertEqual(row["model"], "qwen2.5:1.5b")
            self.assertEqual(row["tokens"], 171)
            self.assertTrue(row["constrained"])
            self.assertEqual(row["prompt_sha256"], "a" * 64)
            self.assertNotIn("messages", row)
            self.assertNotIn("reply", row)
            self.assertNotIn("depot-12", json.dumps(row))

    def test_content_is_written_only_when_asked_for(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "t.jsonl"
            JsonlSink(path, send_content=True)(
                RECORD, "qwen2.5:1.5b", MESSAGES, REPLY)
            row = rows(path)[0]
            self.assertEqual(row["messages"], ["At depot-12, add 0.35 bar."])
            self.assertEqual(row["reply"], '{"asserts": false}')

    def test_calls_append_rather_than_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "t.jsonl"
            sink = JsonlSink(path)
            for _ in range(3):
                sink(RECORD, "m", MESSAGES, REPLY)
            self.assertEqual(len(rows(path)), 3)

    def test_a_missing_parent_directory_is_created(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "nested" / "deeper" / "t.jsonl"
            JsonlSink(path)(RECORD, "m", MESSAGES, REPLY)
            self.assertEqual(len(rows(path)), 1)

    def test_a_reply_without_a_message_does_not_raise(self):
        """Ollama's shapes vary and an exporter must not be the thing that
        turns an odd reply into a failed run."""
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "t.jsonl"
            JsonlSink(path, send_content=True)(RECORD, "m", MESSAGES, {})
            self.assertIsNone(rows(path)[0]["reply"])


class TestHostClassification(unittest.TestCase):
    def test_local_hosts(self):
        for host in ("http://localhost:3000", "http://127.0.0.1:3000",
                     "localhost:3000", "http://host.docker.internal:3000"):
            self.assertTrue(_is_local(host), host)

    def test_a_hosted_service_is_not_local(self):
        for host in ("https://cloud.langfuse.com",
                     "https://us.cloud.langfuse.com",
                     "https://langfuse.example.com"):
            self.assertFalse(_is_local(host), host)

    def test_a_host_named_to_look_local_is_not_local(self):
        """`localhost.evil.com` resolves to someone else's machine."""
        self.assertFalse(_is_local("https://localhost.evil.com"))


class TestSinksCannotBreakTheCall(unittest.TestCase):
    class _Client(OllamaClient):
        """Replaces the one network call, so the sink path is exercised
        without a model."""

        def _post(self, path, payload):
            return {"message": {"content": "{}"},
                    "prompt_eval_count": 10, "eval_count": 5}

    def test_a_raising_sink_does_not_fail_the_call(self):
        client = self._Client()

        def explode(*_args, **_kwargs):
            raise RuntimeError("the exporter is down")

        client.add_sink(explode)
        result = client.chat(model="m", messages=MESSAGES)
        self.assertEqual(result["message"]["content"], "{}")
        self.assertEqual(len(client.calls), 1,
                         "the ledger is the record of truth and must survive")

    def test_every_sink_runs_even_if_an_earlier_one_raises(self):
        client = self._Client()
        seen = []
        client.add_sink(lambda *a, **k: (_ for _ in ()).throw(RuntimeError()))
        client.add_sink(lambda record, *a, **k: seen.append(record.model))
        client.chat(model="m", messages=MESSAGES)
        self.assertEqual(seen, ["m"])

    def test_the_schema_is_passed_through_and_recorded(self):
        client = self._Client()
        client.chat(model="m", messages=MESSAGES, schema={"type": "object"})
        self.assertTrue(client.calls[0].constrained)

    def test_an_unconstrained_call_records_that(self):
        client = self._Client()
        client.chat(model="m", messages=MESSAGES)
        self.assertFalse(client.calls[0].constrained)

    def test_a_sink_receives_the_record_the_ledger_kept(self):
        client = self._Client()
        seen = []
        client.add_sink(lambda record, *a, **k: seen.append(record))
        client.chat(model="m", messages=MESSAGES)
        self.assertIs(seen[0], client.calls[0])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
