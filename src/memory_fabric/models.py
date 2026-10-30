"""Bring your own model: one client for every provider, with every call logged.

Every model-backed feature (the free-text claim check, answerability judges,
summaries) takes a model **you** choose, named by one string:

    anthropic:claude-opus-5-5          Anthropic API (pip install ".[claude]")
    openai:gpt-4.1-mini                OpenAI
    azure:my-deployment                Azure OpenAI (MF_AZURE_ENDPOINT)
    gemini:gemini-2.5-flash            Google, via its OpenAI-compatible endpoint
    openrouter:meta-llama/llama-3.3-70b-instruct
    groq:llama-3.3-70b-versatile
    together:..., mistral:..., deepseek:..., fireworks:...
    ollama:qwen2.5:7b                  local, no key
    lmstudio:local-model               local, no key
    vllm:my-model                      any OpenAI-compatible server (MF_VLLM_URL)
    compat:<model>@<base url>          any other OpenAI-compatible endpoint
    claude-cli:sonnet                  the `claude` command line, already signed in

Keys are read from environment variables at call time (`ANTHROPIC_API_KEY`,
`OPENAI_API_KEY`, ...; `memory-fabric models` lists which are set). They are
never stored, logged or written to the event log.

**One wrapper, logged** (AGENTS.md: model, prompt hash, token counts and cost
for every call). `CallLog` keeps each call's provider, model, a SHA-256 of
the prompt (never the prompt), input and output tokens, seconds, and cost.
Cost is computed only from prices **you** configure (`prices=`), because a
price table shipped in a package is wrong the day a provider changes it;
without one, cost is reported as unknown rather than guessed.

The default model is whatever `MEMORY_FABRIC_MODEL` names, so a deployment
switches every feature's model in one place.
"""

from __future__ import annotations

__stability__ = "beta"

import hashlib
import json
import os
import shutil
import subprocess
import threading
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping

ENV_MODEL = "MEMORY_FABRIC_MODEL"

# provider -> (base URL or env var naming it, env var holding the key or None)
OPENAI_COMPATIBLE: dict[str, tuple[str, str | None]] = {
    "openai": ("https://api.openai.com/v1", "OPENAI_API_KEY"),
    "gemini": ("https://generativelanguage.googleapis.com/v1beta/openai", "GEMINI_API_KEY"),
    "openrouter": ("https://openrouter.ai/api/v1", "OPENROUTER_API_KEY"),
    "groq": ("https://api.groq.com/openai/v1", "GROQ_API_KEY"),
    "together": ("https://api.together.xyz/v1", "TOGETHER_API_KEY"),
    "mistral": ("https://api.mistral.ai/v1", "MISTRAL_API_KEY"),
    "deepseek": ("https://api.deepseek.com/v1", "DEEPSEEK_API_KEY"),
    "fireworks": ("https://api.fireworks.ai/inference/v1", "FIREWORKS_API_KEY"),
    "ollama": ("http://127.0.0.1:11434/v1", None),
    "lmstudio": ("http://127.0.0.1:1234/v1", None),
    "vllm": ("$MF_VLLM_URL", "MF_VLLM_API_KEY"),
}
PROVIDERS = ("anthropic", "azure", "compat", "claude-cli", *OPENAI_COMPATIBLE)


class ModelError(RuntimeError):
    pass


@dataclass(frozen=True)
class ModelSpec:
    provider: str
    model: str
    base_url: str | None = None

    @staticmethod
    def parse(text: str) -> "ModelSpec":
        """`provider:model`, or `compat:model@https://host/v1`."""
        if ":" not in text:
            raise ValueError(f"name a provider and a model, like anthropic:claude-opus-5-5 "
                             f"(got {text!r}); providers: {', '.join(PROVIDERS)}")
        provider, model = text.split(":", 1)
        provider = provider.strip().lower()
        if provider not in PROVIDERS:
            raise ValueError(f"unknown provider {provider!r}; one of {', '.join(PROVIDERS)}")
        base = None
        if provider == "compat":
            if "@" not in model:
                raise ValueError("compat needs a base URL: compat:<model>@https://host/v1")
            model, base = model.rsplit("@", 1)
        if not model:
            raise ValueError("model name is empty")
        return ModelSpec(provider, model, base)

    def __str__(self) -> str:
        return f"{self.provider}:{self.model}" + (f"@{self.base_url}" if self.base_url else "")


@dataclass
class Completion:
    text: str
    model: str
    provider: str
    input_tokens: int | None
    output_tokens: int | None
    seconds: float
    cost_usd: float | None
    prompt_hash: str


@dataclass
class CallLog:
    """Every call, without prompts or keys. Optionally appended to a JSONL file."""

    path: str | None = None
    calls: list[dict[str, Any]] = field(default_factory=list)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def record(self, c: Completion) -> None:
        row = {k: v for k, v in asdict(c).items() if k != "text"}
        row["ts"] = time.time()
        with self._lock:
            self.calls.append(row)
            if self.path:
                with open(self.path, "a", encoding="utf-8") as fh:
                    fh.write(json.dumps(row) + "\n")

    def totals(self) -> dict[str, Any]:
        known = [c["cost_usd"] for c in self.calls if c["cost_usd"] is not None]
        return {"calls": len(self.calls),
                "input_tokens": sum(c["input_tokens"] or 0 for c in self.calls),
                "output_tokens": sum(c["output_tokens"] or 0 for c in self.calls),
                "cost_usd": round(sum(known), 6) if known else None,
                "cost_unknown_calls": len(self.calls) - len(known)}


Opener = Callable[..., Any]


class ModelClient:
    """`complete(system, prompt)` against the chosen model.

    `prices` maps a model name to (USD per million input tokens, per million
    output tokens), for cost accounting. `opener` and `runner` replace the
    network and subprocess calls in tests.
    """

    def __init__(self, spec: ModelSpec | str | None = None, *,
                 prices: Mapping[str, tuple[float, float]] | None = None,
                 log: CallLog | None = None, timeout: float = 120.0,
                 opener: Opener | None = None, runner: Callable[..., Any] | None = None,
                 anthropic_client: Any = None) -> None:
        if spec is None:
            spec = os.environ.get(ENV_MODEL)
            if not spec:
                raise ModelError(f"no model chosen: pass one, or set {ENV_MODEL} "
                                 "(for example anthropic:claude-opus-5-5 or ollama:qwen2.5:7b)")
        self.spec = ModelSpec.parse(spec) if isinstance(spec, str) else spec
        self.prices = dict(prices or {})
        self.log = log or CallLog()
        self.timeout = timeout
        self._open = opener or urllib.request.urlopen
        self._run = runner or subprocess.run
        self._anthropic = anthropic_client

    # -- public ---------------------------------------------------------------

    def complete(self, prompt: str, system: str = "", max_tokens: int = 1024) -> Completion:
        digest = hashlib.sha256(f"{system}\0{prompt}".encode("utf-8")).hexdigest()
        started = time.perf_counter()
        p = self.spec.provider
        if p == "anthropic":
            text, tin, tout = self._anthropic_call(prompt, system, max_tokens)
        elif p == "claude-cli":
            text, tin, tout = self._cli_call(prompt, system)
        else:
            text, tin, tout = self._compat_call(prompt, system, max_tokens)
        done = Completion(text=text, model=self.spec.model, provider=p, input_tokens=tin,
                          output_tokens=tout, seconds=round(time.perf_counter() - started, 3),
                          cost_usd=self._cost(tin, tout), prompt_hash=digest)
        self.log.record(done)
        return done

    # -- providers ------------------------------------------------------------

    def _anthropic_call(self, prompt: str, system: str, max_tokens: int) -> tuple[str, Any, Any]:
        client = self._anthropic
        if client is None:
            try:
                import anthropic
            except ImportError as exc:
                raise ModelError('anthropic: pip install ".[claude]"') from exc
            if not os.environ.get("ANTHROPIC_API_KEY"):
                raise ModelError("anthropic: ANTHROPIC_API_KEY is not set")
            client = anthropic.Anthropic(timeout=self.timeout)
            self._anthropic = client
        kwargs: dict[str, Any] = {"model": self.spec.model, "max_tokens": max_tokens,
                                  "messages": [{"role": "user", "content": prompt}]}
        if system:
            kwargs["system"] = system
        try:
            msg = client.messages.create(**kwargs)
        except Exception as exc:  # noqa: BLE001 - the SDK's errors, surfaced as ours
            raise ModelError(f"anthropic: {type(exc).__name__}: {exc}") from exc
        if getattr(msg, "stop_reason", None) == "refusal":
            raise ModelError("anthropic: the model declined this request")
        text = "".join(getattr(b, "text", "") for b in msg.content
                       if getattr(b, "type", "") == "text")
        usage = getattr(msg, "usage", None)
        return text, getattr(usage, "input_tokens", None), getattr(usage, "output_tokens", None)

    def _endpoint(self) -> tuple[str, dict[str, str]]:
        p = self.spec.provider
        headers = {"Content-Type": "application/json"}
        if p == "compat":
            base, key_env = self.spec.base_url or "", "MF_COMPAT_API_KEY"
        elif p == "azure":
            endpoint = os.environ.get("MF_AZURE_ENDPOINT", "").rstrip("/")
            if not endpoint:
                raise ModelError("azure: set MF_AZURE_ENDPOINT to https://<resource>.openai.azure.com")
            version = os.environ.get("MF_AZURE_API_VERSION", "2024-10-21")
            url = (f"{endpoint}/openai/deployments/{self.spec.model}/chat/completions"
                   f"?api-version={version}")
            key = os.environ.get("AZURE_OPENAI_API_KEY")
            if not key:
                raise ModelError("azure: AZURE_OPENAI_API_KEY is not set")
            headers["api-key"] = key
            return url, headers
        else:
            base, key_env = OPENAI_COMPATIBLE[p]  # type: ignore[assignment]
        if base.startswith("$"):
            base = os.environ.get(base[1:], "")
            if not base:
                raise ModelError(f"{p}: set {OPENAI_COMPATIBLE[p][0][1:]} to the server's /v1 URL")
        if key_env:
            key = os.environ.get(key_env)
            if key:
                headers["Authorization"] = "Bearer " + key
            elif p not in ("vllm", "compat"):
                raise ModelError(f"{p}: {key_env} is not set")
        return base.rstrip("/") + "/chat/completions", headers

    def _compat_call(self, prompt: str, system: str, max_tokens: int) -> tuple[str, Any, Any]:
        url, headers = self._endpoint()
        messages = ([{"role": "system", "content": system}] if system else []) + [
            {"role": "user", "content": prompt}]
        body: dict[str, Any] = {"messages": messages, "max_tokens": max_tokens}
        if self.spec.provider != "azure":
            body["model"] = self.spec.model
        request = urllib.request.Request(url, data=json.dumps(body).encode(), headers=headers,
                                         method="POST")
        try:
            with self._open(request, timeout=self.timeout) as response:
                data = json.loads(response.read())
        except urllib.error.HTTPError as exc:
            detail = exc.read()[:300].decode("utf-8", "replace")
            raise ModelError(f"{self.spec.provider}: HTTP {exc.code}: {detail}") from None
        except (urllib.error.URLError, OSError, ValueError) as exc:
            raise ModelError(f"{self.spec.provider}: {type(exc).__name__}: {exc}") from None
        try:
            text = data["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError):
            raise ModelError(f"{self.spec.provider}: unexpected response shape") from None
        usage = data.get("usage") or {}
        return text, usage.get("prompt_tokens"), usage.get("completion_tokens")

    def _cli_call(self, prompt: str, system: str) -> tuple[str, Any, Any]:
        if self._run is subprocess.run and shutil.which("claude") is None:
            raise ModelError("claude-cli: the `claude` command is not installed")
        cmd = ["claude", "-p", prompt, "--model", self.spec.model, "--tools", "",
               "--setting-sources", "", "--output-format", "json"]
        if system:
            cmd += ["--system-prompt", system]
        try:
            proc = self._run(cmd, capture_output=True, text=True, timeout=self.timeout,
                             cwd=str(Path.home()))
            data = json.loads(proc.stdout or "{}")
        except (subprocess.TimeoutExpired, ValueError) as exc:
            raise ModelError(f"claude-cli: {type(exc).__name__}") from None
        if data.get("is_error"):
            raise ModelError(f"claude-cli: {str(data.get('result'))[:200]}")
        usage = data.get("usage") or {}
        self._cli_cost = data.get("total_cost_usd")
        return (str(data.get("result") or ""), usage.get("input_tokens"),
                usage.get("output_tokens"))

    def _cost(self, tin: int | None, tout: int | None) -> float | None:
        if self.spec.provider == "claude-cli" and getattr(self, "_cli_cost", None) is not None:
            return float(self._cli_cost)
        price = self.prices.get(self.spec.model)
        if price is None or tin is None or tout is None:
            return None
        return round(tin * price[0] / 1e6 + tout * price[1] / 1e6, 8)


def configured() -> list[dict[str, Any]]:
    """Which providers this machine can use now, judged by environment only."""
    rows = []
    for p in PROVIDERS:
        if p == "anthropic":
            key = "ANTHROPIC_API_KEY"
        elif p == "azure":
            key = "AZURE_OPENAI_API_KEY"
        elif p == "compat":
            rows.append({"provider": p, "needs": "a base URL in the spec; MF_COMPAT_API_KEY if it wants one",
                         "ready": True})
            continue
        elif p == "vllm":
            key = "MF_VLLM_URL"
        elif p == "claude-cli":
            rows.append({"provider": p, "needs": "the claude command",
                         "ready": shutil.which("claude") is not None})
            continue
        else:
            key = OPENAI_COMPATIBLE[p][1] or "a local server (no key)"
        local = p in OPENAI_COMPATIBLE and OPENAI_COMPATIBLE[p][1] is None
        ready = local or bool(os.environ.get(key.split(" ")[0]))
        rows.append({"provider": p, "needs": key, "ready": ready})
    return rows
