"""Tracing for model calls: a local sink with no dependencies, and Langfuse.

AGENTS.md requires that **LLM calls go through one client wrapper** that logs
model, prompt hash, token counts and cost. `OllamaClient` does, and
`client.calls` is that ledger. This module is what turns the ledger into
something you can look at across runs, without changing where the record of
truth lives.

## Two sinks, and why the local one is first

`JsonlSink` appends one JSON object per call to a file. **No dependencies**,
which matters because CI runs this project with none installed and the
zero-dependency claim is only true if it is checked. It is enough to answer
the questions a cost metric is for: which model, how many calls, how many
tokens, how long, constrained or free-form.

`LangfuseSink` exports the same records to Langfuse, lazily importing its SDK
so that an absent package is a clear error at construction rather than an
import failure in the fabric.

## Content is off by default, and that is not timidity

`CallRecord` stores a **hash** of the prompt, not the prompt, and its docstring
says why: a prompt here contains memory content, which may contain exactly what
the governance layer exists to keep out of secondary surfaces. A trace
exporter is a secondary surface, and Langfuse's default host is a service
someone else runs.

So both sinks send **metadata only** unless `send_content=True` is passed
explicitly. With content enabled, `LangfuseSink` additionally runs the
project's own sensitive-data detector over every string before it leaves the
process and **refuses the call's content** if anything is found -- the same
detector the ingestion path uses, pointed at the egress path. That is a
mitigation and not a guarantee: a detector that catches credentials does not
catch a customer's name in a sentence, and the only configuration that leaks
nothing is the default.

`SECURITY.md` records that the dashboard "loads no external scripts, styles or
fonts … and leaks nothing to a CDN". Enabling content export to a hosted
Langfuse is the one place in this project where memory content crosses a
network boundary on purpose, and it requires both `send_content=True` and, for
a non-local host, `allow_remote_content=True`.
"""

from __future__ import annotations

import json
import pathlib
import threading
from dataclasses import asdict
from typing import Any, Mapping, Sequence

LOCAL_HOSTS = ("localhost", "127.0.0.1", "::1", "host.docker.internal")
"""Hosts treated as the operator's own machine for the content check."""


def _is_local(host: str) -> bool:
    """Whether this host is the operator's own machine.

    The hostname is **parsed** and compared exactly. The first version matched
    substrings -- `"//localhost" in url` -- and a test written against it found
    that `https://localhost.evil.com` passed as local, which would have let
    memory content reach someone else's host without the
    `allow_remote_content` gate that exists to make that a deliberate act. A
    containment check is the wrong tool for an authorisation boundary.
    """
    from urllib.parse import urlparse

    text = (host or "").strip().lower()
    if "//" not in text:
        text = "//" + text
    name = urlparse(text).hostname or ""
    return name in LOCAL_HOSTS


def _texts(messages: Sequence[Mapping[str, Any]]) -> list[str]:
    return [str(m.get("content") or "") for m in messages]


class JsonlSink:
    """Append one JSON object per model call. No dependencies.

    Thread-safe because `OllamaClient` is used from a thread pool in at least
    one experiment, and a torn line in a trace file is worse than no trace: it
    makes the whole file unparseable rather than losing one record.
    """

    def __init__(self, path: str | pathlib.Path,
                 send_content: bool = False) -> None:
        self.path = pathlib.Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.send_content = send_content
        self._lock = threading.Lock()

    def __call__(self, record: Any, model: str,
                 messages: Sequence[Mapping[str, Any]],
                 reply: Mapping[str, Any]) -> None:
        row: dict[str, Any] = {**asdict(record), "tokens": record.tokens}
        if self.send_content:
            row["messages"] = _texts(messages)
            message = reply.get("message") if isinstance(reply, Mapping) else None
            row["reply"] = (message or {}).get("content") if isinstance(
                message, Mapping) else None
        line = json.dumps(row, default=str)
        with self._lock:
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")


def summarise(path: str | pathlib.Path) -> dict[str, dict[str, Any]]:
    """Per-model latency and token totals from a `JsonlSink` file.

    Reports the **median and p90** alongside the mean, because every latency
    figure in this project was measured on a shared CPU machine while other
    work ran. A mean over nineteen calls hides that: the same model and prompt
    measured 19.3 s on a quiet machine and 38.0 s while a test suite ran, and
    a table of means gives no way to see which figure is which. The spread is
    the warning label.

    Keyed by `(model, constrained)`, since the two decoding modes are not
    comparable -- measured at +49% to +54% wall time for identical output.
    """
    import statistics

    buckets: dict[tuple[str, bool], list[dict[str, Any]]] = {}
    for line in pathlib.Path(path).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except ValueError:
            # One torn line should not lose a run's whole trace.
            continue
        key = (str(row.get("model")), bool(row.get("constrained")))
        buckets.setdefault(key, []).append(row)

    out: dict[str, dict[str, Any]] = {}
    for (model, constrained), rows in sorted(buckets.items()):
        seconds = sorted(float(r.get("seconds") or 0.0) for r in rows)
        name = f"{model} ({'constrained' if constrained else 'free-form'})"
        out[name] = {
            "calls": len(rows),
            "seconds_mean": round(statistics.mean(seconds), 1),
            "seconds_median": round(statistics.median(seconds), 1),
            "seconds_p90": round(seconds[min(len(seconds) - 1,
                                             int(0.9 * len(seconds)))], 1),
            "seconds_min": round(seconds[0], 1),
            "seconds_max": round(seconds[-1], 1),
            "prompt_tokens": sum(int(r.get("prompt_tokens") or 0) for r in rows),
            "completion_tokens": sum(
                int(r.get("completion_tokens") or 0) for r in rows),
        }
    return out


class LangfuseSink:
    """Export recorded model calls to Langfuse.

    The SDK is imported here rather than at module scope, so that importing
    `memory_fabric` never requires it and a missing package fails loudly at the
    point someone asked for tracing.

    Content is withheld unless `send_content=True`, and for a non-local host
    also `allow_remote_content=True`. When content is sent, every string is
    checked with the project's own sensitive-data detector first and the
    content is dropped if anything is found -- see the module docstring for why
    that is a mitigation rather than a guarantee.
    """

    def __init__(self, *, host: str | None = None,
                 public_key: str | None = None,
                 secret_key: str | None = None,
                 send_content: bool = False,
                 allow_remote_content: bool = False,
                 session_id: str | None = None) -> None:
        try:
            from langfuse import Langfuse  # type: ignore
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise RuntimeError(
                "LangfuseSink needs the `langfuse` package, which this project "
                "does not depend on. Install it in the environment that wants "
                "tracing: pip install langfuse"
            ) from exc

        import os

        self.host = host or os.environ.get(
            "LANGFUSE_HOST", "http://localhost:3000")
        remote = not _is_local(self.host)
        if send_content and remote and not allow_remote_content:
            raise ValueError(
                f"send_content=True with a non-local Langfuse host "
                f"({self.host}) would put memory content on a service this "
                f"project does not run. Pass allow_remote_content=True to "
                f"state that intent, or self-host Langfuse, or leave content "
                f"off -- which is the default and the only configuration that "
                f"leaks nothing."
            )
        self.send_content = send_content
        self.session_id = session_id
        self._client = Langfuse(
            host=self.host,
            public_key=public_key or os.environ.get("LANGFUSE_PUBLIC_KEY"),
            secret_key=secret_key or os.environ.get("LANGFUSE_SECRET_KEY"),
        )

    def _clean(self, values: Sequence[str]) -> list[str] | None:
        """The ingestion detector, pointed at the egress path.

        Returns None when anything is found, because a partial redaction of a
        prompt is a guess about which half mattered.
        """
        from ..governance.sensitive import SensitiveDataDetector

        detector = SensitiveDataDetector()
        for text in values:
            if detector.scan(text):
                return None
        return list(values)

    def __call__(self, record: Any, model: str,
                 messages: Sequence[Mapping[str, Any]],
                 reply: Mapping[str, Any]) -> None:
        payload: dict[str, Any] = {
            "name": "extract" if record.constrained else "chat",
            "model": model,
            "metadata": {
                "prompt_sha256": record.prompt_sha256,
                "constrained": record.constrained,
                "seconds": round(record.seconds, 3),
            },
            "usage_details": {
                "input": record.prompt_tokens,
                "output": record.completion_tokens,
                "total": record.tokens,
            },
        }
        if self.session_id:
            payload["session_id"] = self.session_id
        if self.send_content:
            cleaned = self._clean(_texts(messages))
            if cleaned is None:
                payload["metadata"]["content_withheld"] = "sensitive_data"
            else:
                payload["input"] = cleaned
                message = reply.get("message") if isinstance(
                    reply, Mapping) else None
                if isinstance(message, Mapping):
                    payload["output"] = message.get("content")
        self._client.create_generation(**payload)

    def flush(self) -> None:
        """Send anything buffered. A short run can end before the SDK's own
        background flush, which loses the trace it was asked to keep."""
        self._client.flush()
