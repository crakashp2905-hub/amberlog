"""PUB-13 (MemoryAgentBench, Conflict_Resolution) and PUB-05 (AA-LCR) with a small local model. Descriptive.

    python -m benchmarks.longctx --suite mab --data DIR --model ollama:qwen2.5:3b [--limit 120]
    python -m benchmarks.longctx --suite aalcr --data DIR --model ollama:qwen2.5:3b [--limit 100]

Same question, same model, same context budget for every arm:

- `none`: the question alone.
- `head` / `tail`: the first / last BUDGET_WORDS of the source material.
- `fabric`: the source split into ~120-word chunks, written to a MemoryFabric
  in order, `retrieve(question, k)` filled to the budget in rank order.

Scoring is lenient and stated: a reply is correct if, normalised, it contains
any gold answer (MemoryAgentBench's own sub-string criterion; for AA-LCR, whose
official grader is a model judge, this under- and over-counts in ways the
result page says). No threshold is registered: there is no evidence-level
oracle for a fair ceiling, so these runs are descriptive.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import random
import re
import sys
import time
import zipfile
from pathlib import Path
from typing import Any, Iterator

ROOT = Path(__file__).resolve().parents[1]
BUDGET_WORDS, CHUNK_WORDS, K = 1200, 120, 12
ARMS = ("none", "head", "tail", "fabric")
SYSTEM = "Answer the question from the material given. Reply with the answer only, as briefly as possible."


def norm(text: str) -> str:
    return " ".join(re.findall(r"[a-z0-9.%$-]+", text.lower()))


def correct(reply: str, gold: list[str]) -> bool:
    r = norm(reply)
    return any(g and norm(g) and norm(g) in r for g in gold)


def chunks(text: str, size: int = CHUNK_WORDS) -> list[str]:
    w = text.split()
    return [" ".join(w[i:i + size]) for i in range(0, len(w), size)]


def fit(texts: list[str], budget: int) -> str:
    out: list[str] = []
    for t in texts:
        room = budget - len(out)
        if room <= 0:
            break
        out += t.split()[:room]
    return " ".join(out)


def items_mab(data: Path, limit: int) -> Iterator[tuple[str, str, list[str], str]]:
    """(group id, question, gold answers, source text)."""
    import pyarrow.parquet as pq

    rows = pq.read_table(data / "Conflict_Resolution.parquet").to_pylist()
    print("MAB layout:", len(rows), "contexts; metadata keys", sorted(rows[0].get("metadata") or {}),
          "answer type", type(rows[0]["answers"][0]).__name__, flush=True)
    picked = []
    for i, r in enumerate(rows):
        for q, a in zip(r["questions"], r["answers"]):
            gold = [str(x) for x in a] if isinstance(a, (list, tuple)) else [str(a)]
            picked.append((f"mab-{i}", str(q), gold, i))
    rng = random.Random(1)
    rng.shuffle(picked)
    per_ctx: dict[int, int] = {}
    cap = max(1, limit // len(rows) + 1)
    n = 0
    for gid, q, gold, i in picked:
        if per_ctx.get(i, 0) >= cap or n >= limit:
            continue
        per_ctx[i] = per_ctx.get(i, 0) + 1
        n += 1
        yield gid, q, gold, rows[i]["context"]


def items_aalcr(data: Path, limit: int) -> Iterator[tuple[str, str, list[str], str]]:
    rows = list(csv.DictReader(io.StringIO((data / "AA-LCR_Dataset.csv").read_text(encoding="utf-8"))))
    archive = zipfile.ZipFile(data / "AA-LCR_extracted-text.zip")
    names = [n for n in archive.namelist() if not n.endswith("/")]
    print("AA-LCR layout:", len(rows), "questions;", len(names), "text files; e.g.", names[:3], flush=True)
    by_stem: dict[str, list[str]] = {}
    for n in names:
        by_stem.setdefault(Path(n).stem.lower(), []).append(n)
        by_stem.setdefault(Path(n).parent.name.lower(), []).append(n)
    for r in rows[:limit]:
        files: list[str] = []
        for fn in re.split(r"[;|\n]+", r.get("data_source_filenames") or ""):
            stem = Path(fn.strip()).stem.lower()
            files += by_stem.get(stem, [])
        if not files:
            files = by_stem.get(str(r.get("document_set_id", "")).lower(), [])
        text = "\n\n".join(archive.read(f).decode("utf-8", errors="replace") for f in dict.fromkeys(files))
        yield f"aalcr-{r.get('question_id')}", r["question"], [r["answer"]], text


def run(suite: str, data: Path, model: str, limit: int) -> dict[str, Any]:
    from memory_fabric import MemoryFabric
    from memory_fabric.models import CallLog, ModelClient

    log = CallLog()
    client = ModelClient(model, log=log, timeout=900)
    items = items_mab(data, limit) if suite == "mab" else items_aalcr(data, limit)
    rows: list[dict[str, Any]] = []
    cache: dict[str, Any] = {}
    started = time.time()
    for gid, question, gold, source in items:
        if not source.strip():
            rows.append({"group": gid, "missing_source": True, **{a: False for a in ARMS}})
            continue
        words = source.split()
        if gid.split("-")[0] + str(hash(source)) not in cache:
            f = MemoryFabric(":memory:", auto_activate=True, encrypt_content=False, recognise_copies=False,
                             retrieval="lexical")
            for c in chunks(source):
                f.remember("source", c, scope="team")
            for old in cache.values():
                old.close()
            cache.clear()
            cache[gid.split("-")[0] + str(hash(source))] = f
        f = cache[gid.split("-")[0] + str(hash(source))]
        ranked = [m.content for m in f.retrieve("reader", question, k=K, min_relevance=0.0).exposed]
        ctx = {"none": "", "head": " ".join(words[:BUDGET_WORDS]), "tail": " ".join(words[-BUDGET_WORDS:]),
               "fabric": fit(ranked, BUDGET_WORDS)}
        out: dict[str, Any] = {"group": gid, "source_words": len(words)}
        for arm in ARMS:
            prompt = (f"Material:\n{ctx[arm]}\n\n" if ctx[arm] else "") + f"Question: {question}\nAnswer:"
            try:
                reply = client.complete(prompt, system=SYSTEM, max_tokens=48).text
            except Exception as exc:  # noqa: BLE001 - a failed call is a wrong answer, recorded
                reply = f"ERROR {type(exc).__name__}"
            out[arm] = correct(reply, gold)
        rows.append(out)
        print(json.dumps({"n": len(rows), "elapsed_s": round(time.time() - started)}), flush=True)
    for old in cache.values():
        old.close()
    return {"rows": rows, "calls": log.totals()}


def main(argv: list[str]) -> int:
    from benchmarks.manifest import Manifest, head
    from benchmarks.manifest import write as write_manifest
    from benchmarks.stats import paired_bootstrap

    p = argparse.ArgumentParser()
    p.add_argument("--suite", choices=["mab", "aalcr"], required=True)
    p.add_argument("--data", required=True, type=Path)
    p.add_argument("--model", default="ollama:qwen2.5:3b")
    p.add_argument("--limit", type=int, default=120)
    args = p.parse_args(argv)
    raw = run(args.suite, args.data, args.model, args.limit)
    rows = [r for r in raw["rows"] if not r.get("missing_source")]
    acc = {a: round(sum(r[a] for r in rows) / len(rows), 4) for a in ARMS} if rows else {}
    paired = {f"fabric-{b}": paired_bootstrap([float(r[b]) for r in rows], [float(r["fabric"]) for r in rows],
                                              seed=1, clusters=[r["group"].rsplit("-", 1)[0] for r in rows])
              for b in ("none", "head", "tail")} if rows else {}
    suite_id, name = ("PUB-13", "pub13-memoryagentbench-local") if args.suite == "mab" else ("PUB-05", "pub05-aa-lcr-local")
    commit = head()[:12]
    data = {"commit": commit, "suite": suite_id, "model": args.model, "budget_words": BUDGET_WORDS, "k": K,
            "n": len(rows), "missing_source": len(raw["rows"]) - len(rows), "accuracy": acc, "paired": paired,
            "usage": raw["calls"], "seeds": [1]}
    print(f"=== {suite_id} JSON ===")
    print(json.dumps(data))
    print(f"=== {suite_id} END ===")
    (ROOT / "research" / "results" / f"{name}.json").write_text(json.dumps(data, indent=1) + "\n", encoding="utf-8")
    write_manifest(Manifest(
        run_id=name, suite=suite_id, arm=",".join(ARMS), decision="DESCRIPTIVE", repo_commit=commit,
        reason="local 3B model, lenient containment scoring, no evidence-level oracle",
        dataset={"name": "MemoryAgentBench Conflict_Resolution (MIT)" if args.suite == "mab" else "AA-LCR (Apache-2.0)"},
        model={"provider": "ollama", "id": args.model}, budget={"context_words": BUDGET_WORDS, "k": K}, seeds=[1],
        counts={"attempted": len(raw["rows"]), "completed": len(rows),
                "solved": round(acc.get("fabric", 0) * len(rows)), "skipped": len(raw["rows"]) - len(rows), "failed": 0},
        results={"primary_metric": "contains-gold accuracy", **acc}, cost={"model_usd": 0.0, "model_calls": raw["calls"].get("calls")},
        verification={"baseline_registered": True, "oracle_sanity_passed": False, "holdout_frozen": True,
                      "independent_replicated": False}))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
