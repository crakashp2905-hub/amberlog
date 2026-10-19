"""A Claude client with the same `chat` interface as `OllamaClient`, so every model-based
evaluation runs on a frontier model unchanged.

    from memory_fabric.adapters.claude_chat import ClaudeChat
    client = ClaudeChat()            # reads ANTHROPIC_API_KEY from the environment
    client.chat("claude-sonnet-5-5", [{"role": "system", "content": "..."},
                                      {"role": "user", "content": "..."}])

Returns Ollama's reply shape (`{"message": {"content": ...}}`) and records
every call as a `CallRecord` (model, prompt hash, tokens), as AGENTS.md
requires. The key is never read here, logged or stored: the official SDK
reads it from the environment.

`schema` asks for JSON matching the schema in the system prompt and
extracts the first JSON object from the reply. Unlike Ollama it is not
enforced during decoding, so callers must already tolerate a reply that
fails to parse (every caller in this repository does).
"""

from __future__ import annotations

__stability__ = "beta"

import hashlib
import json
import re
import time
from typing import Any, Mapping, Sequence

from .ollama import CallRecord

DEFAULT_MODEL = "claude-sonnet-5-5"


class ClaudeChat:
    def __init__(self, client: Any = None) -> None:
        if client is None:
            import anthropic

            client = anthropic.Anthropic()
        self.client = client
        self.calls: list[CallRecord] = []

    def chat(self, model: str, messages: Sequence[Mapping[str, Any]],
             tools: Sequence[Mapping[str, Any]] | None = None, temperature: float = 0.0,
             num_predict: int = 256, schema: Mapping[str, Any] | None = None,
             think: bool | None = None) -> dict[str, Any]:
        system = "\n\n".join(str(m["content"]) for m in messages if m.get("role") == "system")
        if schema:
            system += ("\n\nRespond with a single JSON object and nothing else, matching this "
                       "JSON schema: " + json.dumps(schema))
        turns = [{"role": m["role"], "content": str(m["content"])} for m in messages
                 if m.get("role") in ("user", "assistant")]
        started = time.perf_counter()
        kwargs: dict[str, Any] = {"model": model, "max_tokens": max(num_predict, 16),
                                  "temperature": temperature, "messages": turns}
        if system:
            kwargs["system"] = system
        reply = self.client.messages.create(**kwargs)
        text = "".join(getattr(block, "text", "") for block in reply.content)
        if schema:
            found = re.search(r"\{.*\}", text, re.S)
            text = found.group(0) if found else text
        usage = getattr(reply, "usage", None)
        out_tokens = int(getattr(usage, "output_tokens", 0) or 0)
        self.calls.append(CallRecord(
            model=model,
            prompt_sha256=hashlib.sha256(json.dumps(list(messages), sort_keys=True,
                                                    default=str).encode()).hexdigest(),
            prompt_tokens=int(getattr(usage, "input_tokens", 0) or 0),
            completion_tokens=out_tokens, seconds=time.perf_counter() - started,
            truncated=getattr(reply, "stop_reason", "") == "max_tokens",
            constrained=bool(schema)))
        return {"message": {"role": "assistant", "content": text}}


def make_client(model: str) -> Any:
    """`ClaudeChat` for a Claude model id, `OllamaClient` for anything else."""
    if model.startswith("claude-"):
        return ClaudeChat()
    from .ollama import OllamaClient

    return OllamaClient()
