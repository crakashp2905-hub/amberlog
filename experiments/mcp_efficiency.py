"""Is the governed MCP server more efficient than what it would replace?

A memory MCP server that most teams would write first is a thin wrapper over a
vector store: `remember` appends, `recall` returns the top-k texts. That is
the baseline here, and it is implemented **through the same protocol layer**
so the comparison is of the memory behind the tools, not of two JSON-RPC
implementations.

## What is measured

* **Latency per call**, in-process -- the server's own cost, separated from
  the host and the model. Median and p95 over many calls, because a mean over
  a shared machine hides the tail, which this project has already been misled
  by once.
* **Tokens the model has to read per recall**, approximated as
  whitespace-separated words of the text content returned. This is the cost
  that recurs on every turn of every conversation, so it dominates any
  per-call latency figure.
* **Store size** at which it is measured, swept, because retrieval cost grows
  with the corpus and a figure at one size is not a figure.

## What "more efficient" can and cannot mean here

The governed server does strictly more work per call -- a sensitive-data scan
on write, lifecycle and tenant gating and a propensity log on read -- so it
**cannot** be faster per call than an append-and-scan baseline, and claiming
otherwise would be the kind of number this project exists not to publish. The
honest questions are whether the overhead is small enough not to matter next to
a model call, and whether it buys a *cheaper context* -- which, after X5, it
should: `compact` rendering returns fewer words than the full governed
rendering while keeping the security control.

The model is not called. Nothing here measures answer quality, which X5 did.
"""

from __future__ import annotations

import argparse
import json
import random
import statistics
import sys
import time
from pathlib import Path
from typing import Any, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from memory_fabric import MemoryFabric  # noqa: E402
from memory_fabric.mcp.protocol import (  # noqa: E402
    META_PROTOCOL, Cache, Handled, Server,
)
from memory_fabric.mcp.tools import build_server  # noqa: E402
from memory_fabric.vectors import LexicalIndex  # noqa: E402

META = {META_PROTOCOL: "2026-07-28"}

SITES = ("coastal", "urban", "cold_store", "harbour", "quarry", "depot-7")
FAULTS = tuple(f"E{n:02d}" for n in range(1, 25))
ACTIONS = ("swap the pilot cable", "reseat the contactor", "replace the RCD",
           "reflash the firmware", "clean the earth bond", "recalibrate")


def corpus(n: int, rng: random.Random) -> list[str]:
    return [f"Fault {rng.choice(FAULTS)} at the {rng.choice(SITES)} site: "
            f"{rng.choice(ACTIONS)}. Observed on unit {rng.randrange(900)}."
            for _ in range(n)]


def naive_server(k_default: int = 5) -> tuple[Server, list[str]]:
    """The memory MCP server most teams would write first.

    Same protocol layer, same tool names for the two that matter, no
    governance: append on write, IDF overlap on read, raw text returned.
    """
    store: list[str] = []
    index = LexicalIndex()
    server = Server(name="naive-memory", version="0",
                    capabilities={"tools": {"listChanged": False}})

    def tools_call(params, ctx):
        name = params.get("name")
        args = params.get("arguments") or {}
        if name == "memory_remember":
            index.add(str(len(store)), args["content"])
            store.append(args["content"])
            return Handled({"content": [{"type": "text",
                                         "text": f"stored {len(store) - 1}"}]})
        if name == "memory_recall":
            hits = index.search(args["query"], k=int(args.get("k", k_default)))
            text = "\n".join(store[int(i)] for i, _ in hits)
            return Handled({"content": [{"type": "text", "text": text}]})
        raise ValueError(name)

    server.methods["tools/call"] = tools_call
    server.methods["tools/list"] = lambda p, c: Handled(
        {"tools": []}, Cache(ttl_ms=0))
    return server, store


def call(server: Server, name: str, arguments: dict) -> tuple[dict, float]:
    started = time.perf_counter()
    response = server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                              "params": {"_meta": META, "name": name,
                                         "arguments": arguments}})
    return response, (time.perf_counter() - started) * 1000.0


def words(response: dict) -> int:
    content = (response.get("result") or {}).get("content") or []
    return sum(len(block.get("text", "").split()) for block in content)


def percentile(values: Sequence[float], q: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(q * len(ordered)))]


def measure(n: int, recalls: int, seed: int) -> dict[str, Any]:
    rng = random.Random(seed)
    texts = corpus(n, rng)
    queries = [f"fault {rng.choice(FAULTS)} {rng.choice(SITES)}"
               for _ in range(recalls)]

    arms: dict[str, Any] = {}
    for arm in ("naive", "governed_compact", "governed_full"):
        if arm == "naive":
            server, _ = naive_server()
            fabric = None
        else:
            fabric = MemoryFabric(":memory:", encrypt_content=False,
                                  retrieval="lexical", auto_activate=True)
            server = build_server(fabric, "agent-a",
                                  rendering=arm.split("_")[1])
        write_ms = []
        for text in texts:
            _, ms = call(server, "memory_remember", {"content": text})
            write_ms.append(ms)
        read_ms, read_words = [], []
        for query in queries:
            response, ms = call(server, "memory_recall", {"query": query, "k": 5})
            read_ms.append(ms)
            read_words.append(words(response))
        if fabric is not None:
            fabric.close()
        arms[arm] = {
            "write_ms_median": round(statistics.median(write_ms), 3),
            "write_ms_p95": round(percentile(write_ms, 0.95), 3),
            "recall_ms_median": round(statistics.median(read_ms), 3),
            "recall_ms_p95": round(percentile(read_ms, 0.95), 3),
            "recall_words_mean": round(statistics.mean(read_words), 1),
        }
    naive = arms["naive"]
    for arm in ("governed_compact", "governed_full"):
        row = arms[arm]
        row["recall_overhead_ms"] = round(
            row["recall_ms_median"] - naive["recall_ms_median"], 3)
        row["words_vs_naive"] = round(
            row["recall_words_mean"] / naive["recall_words_mean"], 3)
    return {"store_size": n, "recalls": recalls, "arms": arms}


def run(sizes: Sequence[int], recalls: int, seed: int) -> dict[str, Any]:
    return {
        "experiment": "mcp-efficiency",
        "note": ("in-process, no model; latency is the server's own cost and "
                 "words are what a model reads per recall"),
        "rows": [measure(n, recalls, seed) for n in sizes],
    }


def to_markdown(result: dict[str, Any]) -> str:
    lines = [
        "# MCP efficiency - the governed server against a naive memory server",
        "",
        "In-process, same protocol layer, no model. Latency is the server's "
        "own cost; words are what a model reads on every recall.",
        "",
        "| store | arm | recall median ms | recall p95 ms | overhead vs naive "
        "| words per recall | words vs naive |",
        "|---|---|---|---|---|---|---|",
    ]
    for row in result["rows"]:
        for arm, data in row["arms"].items():
            lines.append(
                f"| {row['store_size']} | `{arm}` | {data['recall_ms_median']} | "
                f"{data['recall_ms_p95']} | "
                f"{data.get('recall_overhead_ms', '-')} | "
                f"{data['recall_words_mean']} | "
                f"{data.get('words_vs_naive', '1.0')} |")
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--sizes", type=int, nargs="*",
                        default=[100, 1000, 5000])
    parser.add_argument("--recalls", type=int, default=200)
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--out")
    args = parser.parse_args(argv)
    result = run(args.sizes, args.recalls, args.seed)
    if args.out:
        Path(args.out).write_text(json.dumps(result, indent=2) + "\n",
                                  encoding="utf-8")
    text = to_markdown(result)
    try:
        print(text)
    except UnicodeEncodeError:
        encoding = sys.stdout.encoding or "ascii"
        print(text.encode(encoding, "replace").decode(encoding, "replace"))
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
