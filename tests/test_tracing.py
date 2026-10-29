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
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from amberlog.adapters.ollama import CallRecord, OllamaClient  # noqa: E402
from amberlog.adapters.tracing import JsonlSink, _is_local  # noqa: E402

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


class TestSummarise(unittest.TestCase):
    """`summarise` reports median and p90 beside the mean because every
    latency figure in this project was measured on a shared CPU machine. The
    same model and prompt measured 19.3 s quiet and 38.0 s while a test suite
    ran, so a table of means gives no way to tell which figure is which."""

    def _write(self, path, rows):
        # `print` rather than `handle.write`, so this file needs no newline
        # escapes -- the first version lost them to a shell heredoc and the
        # module would not parse.
        with path.open("w", encoding="utf-8") as handle:
            for row in rows:
                print(json.dumps(row), file=handle)

    def _row(self, model, seconds, constrained=True):
        return {"model": model, "seconds": seconds,
                "constrained": constrained, "prompt_tokens": 100,
                "completion_tokens": 50}

    def test_the_spread_is_reported_not_just_the_mean(self):
        from amberlog.adapters.tracing import summarise

        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "t.jsonl"
            # One contended outlier among nine quiet calls: the mean moves a
            # little and the max moves a lot, which is the point.
            self._write(path, [self._row("m", s) for s in
                               [10, 10, 10, 10, 10, 10, 10, 10, 10, 100]])
            out = summarise(path)["m (constrained)"]
            self.assertEqual(out["calls"], 10)
            self.assertEqual(out["seconds_median"], 10.0)
            self.assertEqual(out["seconds_max"], 100.0)
            self.assertEqual(out["seconds_min"], 10.0)
            self.assertEqual(out["seconds_mean"], 19.0)

    def test_the_two_decoding_modes_are_separate_buckets(self):
        """They are not comparable -- measured at +49% to +54% wall time for
        identical output -- so averaging across them would invent a figure
        describing neither."""
        from amberlog.adapters.tracing import summarise

        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "t.jsonl"
            self._write(path, [self._row("m", 10, True),
                               self._row("m", 20, False)])
            out = summarise(path)
            self.assertEqual(sorted(out), ["m (constrained)", "m (free-form)"])
            self.assertEqual(out["m (constrained)"]["seconds_mean"], 10.0)
            self.assertEqual(out["m (free-form)"]["seconds_mean"], 20.0)

    def test_tokens_are_totalled_per_bucket(self):
        from amberlog.adapters.tracing import summarise

        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "t.jsonl"
            self._write(path, [self._row("m", 10)] * 3)
            out = summarise(path)["m (constrained)"]
            self.assertEqual(out["prompt_tokens"], 300)
            self.assertEqual(out["completion_tokens"], 150)

    def test_a_torn_line_does_not_lose_the_rest_of_the_trace(self):
        """A run long enough to need a trace is long enough to be killed
        mid-write, and one bad line should cost one call, not the file."""
        from amberlog.adapters.tracing import summarise

        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "t.jsonl"
            with path.open("w", encoding="utf-8") as handle:
                print(json.dumps(self._row("m", 10)), file=handle)
                print('{"model": "m", "seco', file=handle)
                print(json.dumps(self._row("m", 12)), file=handle)
            self.assertEqual(summarise(path)["m (constrained)"]["calls"], 2)

    def test_a_single_call_does_not_index_out_of_range(self):
        from amberlog.adapters.tracing import summarise

        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "t.jsonl"
            self._write(path, [self._row("m", 7)])
            out = summarise(path)["m (constrained)"]
            self.assertEqual(out["seconds_p90"], 7.0)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
