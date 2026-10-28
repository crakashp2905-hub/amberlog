"""PUB-06: PersonaMem with a small local model (research/prereg/pm1-personamem-local.md). Descriptive.

    python -m benchmarks.personamem --data DIR --model ollama:qwen2.5:3b [--limit 120]

DIR holds `questions_32k.csv` and `shared_contexts_32k.jsonl` from
bowen-upenn/PersonaMem (MIT). Nothing from the dataset is executed or committed;
only aggregate numbers are written.
"""

from __future__ import annotations

import argparse
import ast
import csv
import json
import random
import re
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
OUT_MD = ROOT / "research" / "results" / "pm1-personamem-local.md"
OUT_JSON = ROOT / "research" / "results" / "pm1-personamem-local.json"
BUDGET_WORDS, K, ARMS = 1200, 12, ("none", "recent", "fabric")
SYSTEM = ("You are a helpful assistant answering a user you have talked with before. "
          "Choose the single best option. Reply with the option letter only, like (b).")


def options_of(raw: str) -> list[str]:
    try:
        value = ast.literal_eval(raw)
        if isinstance(value, (list, tuple)):
            return [str(v) for v in value]
    except (ValueError, SyntaxError):
        pass
    return [o.strip() for o in re.split(r"\n+", raw) if o.strip()]


def letter(text: str) -> str | None:
    m = re.search(r"\(([a-z])\)", text.lower()) or re.search(r"\b([a-d])\b", text.lower())
    return m[1] if m else None


def words(text: str) -> list[str]:
    return text.split()


def fit(texts: list[str], budget: int) -> str:
    out: list[str] = []
    for t in texts:
        room = budget - len(out)
        if room <= 0:
            break
        out += words(t)[:room]
    return " ".join(out)


def sample(rows: list[dict[str, str]], limit: int) -> list[dict[str, str]]:
    by_type: dict[str, list[dict[str, str]]] = defaultdict(list)
    for r in rows:
        by_type[r["question_type"]].append(r)
    rng = random.Random(1)
    per = max(1, limit // len(by_type))
    picked = []
    for t in sorted(by_type):
        picked += rng.sample(by_type[t], min(per, len(by_type[t])))
    rng.shuffle(picked)
    return picked[:limit] if len(picked) >= limit else picked


def messages(context: list[dict[str, str]], end: int) -> list[str]:
    return [f"{m.get('role', '')}: {m.get('content', '')}" for m in context[:end + 1]
            if m.get("role") != "system"]


def prompt(question: str, opts: list[str], ctx: str) -> str:
    head = f"Earlier conversation (excerpts):\n{ctx}\n\n" if ctx else ""
    return f"{head}User now says: {question}\n\nOptions:\n" + "\n".join(opts) + "\n\nAnswer with the letter."


def run(data: Path, model: str, limit: int) -> dict[str, Any]:
    from memory_fabric import MemoryFabric
    from memory_fabric.models import CallLog, ModelClient

    rows = list(csv.DictReader(open(data / "questions_32k.csv", encoding="utf-8")))
    contexts: dict[str, list[dict[str, str]]] = {}
    with open(data / "shared_contexts_32k.jsonl", encoding="utf-8") as fh:
        for line in fh:
            contexts.update(json.loads(line))
    log = CallLog()
    client = ModelClient(model, log=log, timeout=900)
    results: list[dict[str, Any]] = []
    started = time.time()
    for row in sample(rows, limit):
        ctx = contexts[row["shared_context_id"]]
        end = int(float(row["end_index_in_shared_context"]))
        msgs = messages(ctx, end)
        opts = options_of(row["all_options"])
        gold = letter(row["correct_answer"])
        f = MemoryFabric(":memory:", auto_activate=True, encrypt_content=False, recognise_copies=False,
                         retrieval="lexical")
        try:
            for m in msgs:
                f.remember("user", m[:4000])
            ranked = [m.content for m in f.retrieve("user", row["user_question_or_message"], k=K,
                                                    min_relevance=0.0).exposed]
        finally:
            f.close()
        recent_words = words(" ".join(msgs))[-BUDGET_WORDS:]
        ctx_by_arm = {"none": "", "recent": " ".join(recent_words), "fabric": fit(ranked, BUDGET_WORDS)}
        out: dict[str, Any] = {"type": row["question_type"], "gold": gold}
        for arm in ARMS:
            try:
                reply = client.complete(prompt(row["user_question_or_message"], opts, ctx_by_arm[arm]),
                                        system=SYSTEM, max_tokens=8).text
            except Exception as exc:  # noqa: BLE001 - a failed call is a wrong answer, recorded
                reply = f"ERROR {type(exc).__name__}"
            out[arm] = letter(reply) == gold and gold is not None
            out[arm + "_parsed"] = letter(reply) is not None
        results.append(out)
        print(json.dumps({"n": len(results), "elapsed_s": round(time.time() - started)}), flush=True)
    return {"rows": results, "calls": log.totals()}


def summarise(rows: list[dict[str, Any]]) -> dict[str, Any]:
    from benchmarks.stats import paired_bootstrap

    acc = {a: round(sum(r[a] for r in rows) / len(rows), 4) for a in ARMS}
    by_type: dict[str, dict[str, float]] = {}
    for t in sorted({r["type"] for r in rows}):
        sub = [r for r in rows if r["type"] == t]
        by_type[t] = {"n": len(sub), **{a: round(sum(r[a] for r in sub) / len(sub), 3) for a in ARMS}}
    ci = {f"fabric-{b}": paired_bootstrap([float(r[b]) for r in rows], [float(r["fabric"]) for r in rows], seed=1)
          for b in ("none", "recent")}
    parsed = {a: round(sum(r[a + "_parsed"] for r in rows) / len(rows), 3) for a in ARMS}
    return {"n": len(rows), "accuracy": acc, "by_type": by_type, "paired": ci, "parsed_share": parsed}


def main(argv: list[str]) -> int:
    from benchmarks.manifest import Manifest, head
    from benchmarks.manifest import write as write_manifest

    p = argparse.ArgumentParser()
    p.add_argument("--data", required=True, type=Path)
    p.add_argument("--model", default="ollama:qwen2.5:3b")
    p.add_argument("--limit", type=int, default=120)
    args = p.parse_args(argv)
    raw = run(args.data, args.model, args.limit)
    s = summarise(raw["rows"])
    commit = head()[:12]
    data = {"commit": commit, "model": args.model, "budget_words": BUDGET_WORDS, "k": K,
            "seeds": [1], "usage": raw["calls"], **s}
    print("=== PM1 JSON ===")
    print(json.dumps(data))
    print("=== PM1 END ===")
    OUT_JSON.write_text(json.dumps(data, indent=1) + "\n", encoding="utf-8")
    write_manifest(Manifest(
        run_id="pm1-personamem-local", suite="PUB-06", arm="none,recent,fabric", decision="DESCRIPTIVE",
        repo_commit=commit, reason="no gold evidence, so no oracle and no threshold (AGENTS.md 8a/8b)",
        dataset={"name": "PersonaMem", "version": "32k", "license_review": "MIT (dataset card)",
                 "sample": f"{s['n']} questions, Random(1), stratified by type"},
        model={"provider": "ollama", "id": args.model}, budget={"context_words": BUDGET_WORDS, "k": K},
        seeds=[1], prereg="research/prereg/pm1-personamem-local.md",
        counts={"attempted": s["n"], "completed": s["n"], "solved": round(s["accuracy"]["fabric"] * s["n"]),
                "skipped": 0, "failed": 0},
        results={"primary_metric": "accuracy", **s["accuracy"]},
        cost={"model_usd": 0.0, "model_calls": raw["calls"].get("calls")},
        verification={"baseline_registered": True, "oracle_sanity_passed": False, "holdout_frozen": True,
                      "independent_replicated": False}))
    rows = "\n".join(f"| {t} | {v['n']} | " + " | ".join(f"{v[a]:.3f}" for a in ARMS) + " |"
                     for t, v in s["by_type"].items())
    ci = s["paired"]
    OUT_MD.write_text(f"""# PM1 — PersonaMem with a small local model (descriptive)

Protocol: [pm1-personamem-local.md](../prereg/pm1-personamem-local.md). `python -m benchmarks.personamem`
at commit `{commit}` in CI, model `{args.model}`, {s['n']} questions of the 32k split (MIT), the same
{BUDGET_WORDS}-word context budget for every arm. Raw numbers: [pm1-personamem-local.json](pm1-personamem-local.json).
**No claim**: PersonaMem has no gold evidence, so there is no oracle and no threshold.

| arm | accuracy | answers parsed |
|---|---|---|
""" + "\n".join(f"| {a} | {s['accuracy'][a]:.3f} | {s['parsed_share'][a]:.2f} |" for a in ARMS) + f"""

Paired differences (bootstrap, seed 1): fabric − none {ci['fabric-none']['diff']:+.3f}
[{ci['fabric-none']['lo']:+.3f}, {ci['fabric-none']['hi']:+.3f}]; fabric − recent {ci['fabric-recent']['diff']:+.3f}
[{ci['fabric-recent']['lo']:+.3f}, {ci['fabric-recent']['hi']:+.3f}].

| question type | n | none | recent | fabric |
|---|---|---|---|---|
{rows}

Model calls: {raw['calls'].get('calls')}; cost $0 (local). TencentDB reports 48% → 76% on PersonaMem with
their own model and harness; that is not comparable to a 3B local model at a 1,200-word budget.
""", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
