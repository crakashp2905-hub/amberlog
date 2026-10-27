"""K1 — a topic tree as a way in, beside search (research/prereg/k1-topic-navigation.md).

    python -m experiments.k1_navigation [--limit 60]
"""

from __future__ import annotations

import argparse
import json
import random
import statistics
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from experiments import longmemeval_bench as lme  # noqa: E402
from memory_fabric import MemoryFabric  # noqa: E402
from memory_fabric.navigation import navigate  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
K = 10
ARMS = ("lexical", "nav", "nav+lexical", "oracle")


def rrf(*lists: list[str], k: int = K) -> list[str]:
    score: dict[str, float] = {}
    for ranked in lists:
        for i, mid in enumerate(ranked):
            score[mid] = score.get(mid, 0.0) + 1.0 / (60 + i + 1)
    return sorted(score, key=lambda m: -score[m])[:k]


def run(instances: list[dict[str, Any]]) -> dict[str, dict[str, list[float]]]:
    out: dict[str, dict[str, list[float]]] = {a: {"recall": [], "ms": []} for a in ARMS}
    for inst in instances:
        gold = {(sid, pos) for sid, s in zip(inst["haystack_session_ids"], inst["haystack_sessions"])
                for pos, t in enumerate(s) if t.get("has_answer")}
        f = MemoryFabric(":memory:", auto_activate=True, encrypt_content=False, recognise_copies=False,
                         retrieval="lexical")
        try:
            mapping = lme._write_history(f, inst)
            as_of = lme.parse_date(inst.get("question_date") or "")
            q = inst["question"]

            def lexical() -> list[str]:
                return [m.id for m in f.retrieve(agent_id="lme", query=q, k=K, min_relevance=0.0,
                                                 as_of=as_of).exposed]

            def nav() -> list[str]:
                ids = navigate(f, "lme", q, k=K, as_of=as_of)
                if len(ids) < K:   # registered: fill from lexical when the topics hold fewer
                    ids += [m for m in lexical() if m not in ids][:K - len(ids)]
                return ids

            arms = {"lexical": lexical, "nav": nav,
                    "nav+lexical": lambda: rrf(nav(), lexical()),
                    "oracle": lambda: [m for m, p in mapping.items() if p in gold][:K]}
            for name, fn in arms.items():
                t0 = time.perf_counter()
                got = fn()
                out[name]["ms"].append((time.perf_counter() - t0) * 1000)
                hits = len({mapping[m] for m in got if m in mapping} & gold)
                out[name]["recall"].append(hits / len(gold) if gold else 0.0)
        finally:
            f.close()
    return out


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--limit", type=int, default=60)
    args = p.parse_args(argv)
    raw = run(lme.load("s", limit=args.limit))
    rows = {a: {"turn_recall": round(statistics.fmean(v["recall"]), 4),
                "p50_ms": round(statistics.median(v["ms"]), 1)} for a, v in raw.items()}
    b = rows["lexical"]["turn_recall"]
    bar = b + 0.25 * (1 - b)
    n = len(raw["lexical"]["recall"])
    gains = []
    for seed in range(1, 6):
        rng = random.Random(seed)
        idx = [rng.randrange(n) for _ in range(n)]
        gains.append(round(statistics.fmean(raw["nav+lexical"]["recall"][i] - raw["lexical"]["recall"][i]
                                            for i in idx), 4))
    verdict = {"B": b, "bar_K1a": round(bar, 4), "gains": gains,
               "K1a": rows["nav+lexical"]["turn_recall"] >= bar and all(g > 0 for g in gains),
               "K1b": rows["nav+lexical"]["p50_ms"] <= 250,
               "ceiling_ok": all(r["turn_recall"] <= rows["oracle"]["turn_recall"] for r in rows.values())}
    commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True,
                            cwd=ROOT).stdout.strip()
    result = {"commit": commit, "instances": n, "rows": rows, "verdict": verdict}
    print("=== K1 JSON ===")
    print(json.dumps(result))
    print("=== K1 END ===")
    (ROOT / "research" / "results" / "k1-topic-navigation.json").write_text(json.dumps(result, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
