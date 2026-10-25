"""R3 — the best retriever the product can ship (research/prereg/r3-best-retriever.md).

Runs in CI (`.github/workflows/retriever-eval.yml`) because it downloads
models and datasets. Baselines run first and are checked before any model
arm (AGENTS.md 8c, 8d).

    python -m experiments.retriever_eval --lme-limit 60
"""

from __future__ import annotations

import argparse
import json
import pathlib
import random
import statistics
import subprocess
import sys
import time
from typing import Any, Callable, Mapping, Sequence

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from experiments import external_bench as sf  # noqa: E402
from experiments import longmemeval_bench as lme  # noqa: E402
from memory_fabric.vectors import VectorIndex, fuse  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent
K = 10
POOL = 30
EMBEDDERS = {
    "bge-small": "BAAI/bge-small-en-v1.5",
    "bge-base": "BAAI/bge-base-en-v1.5",
    "arctic-m": "snowflake/snowflake-arctic-embed-m",
    "nomic": "nomic-ai/nomic-embed-text-v1.5",
}
RERANKERS = {
    "minilm": "Xenova/ms-marco-MiniLM-L-6-v2",
    "bge-rr": "BAAI/bge-reranker-base",
    "jina-turbo": "jinaai/jina-reranker-v1-turbo-en",
}
RERANK_BASES = ("lexical", "bge-small_hybrid")

_embedders: dict[str, Any] = {}
_rerankers: dict[str, Any] = {}
missing: dict[str, str] = {}


def embedder(name: str):
    if name not in _embedders:
        from memory_fabric.retrievers import FastEmbedEmbedder

        _embedders[name] = FastEmbedEmbedder(EMBEDDERS[name], batch_size=64)
    return _embedders[name]


def reranker(name: str):
    if name not in _rerankers:
        from memory_fabric.retrievers import CrossEncoderReranker

        _rerankers[name] = CrossEncoderReranker(RERANKERS[name], pool=POOL)
    return _rerankers[name]


# --- SciFact arms: query -> ranked doc ids ----------------------------------

def scifact_arms(data: sf.Dataset) -> dict[str, Callable[[], Callable[[str], list[str]]]]:
    lexical = sf._lexical_index(data)

    def lex(k: int):
        return lambda q: [d for d, _ in lexical.search(q, k=k, min_relevance=0.0)]

    def vector_index(name: str) -> VectorIndex:
        return sf._vector_index(data, embedder(name))

    def vec(name: str):
        def build():
            index = vector_index(name)
            return lambda q: [d for d, _ in index.search(q, k=K, min_relevance=0.0)]
        return build

    def hybrid(name: str, k: int = K):
        def build():
            index = vector_index(name)
            return lambda q: [d for d, _ in fuse(index.search(q, k=k, min_relevance=0.0),
                                                 lexical.search(q, k=k, min_relevance=0.0),
                                                 k=k)]
        return build

    def reranked(base: Callable[[], Callable[[str], list[str]]], rr: str):
        def build():
            pool = base()
            model = reranker(rr)

            def run(q: str) -> list[str]:
                ids = pool(q)
                scores = model.score(q, [data.corpus[d] for d in ids])
                order = sorted(range(len(ids)), key=lambda i: (-scores[i], i))
                return [ids[i] for i in order][:K]
            return run
        return build

    arms: dict[str, Callable[[], Callable[[str], list[str]]]] = {
        "lexical": lambda: lex(K),
        "hashing_hybrid": lambda: sf.arm_hashing_hybrid(data, K),
    }
    for name in EMBEDDERS:
        arms[f"{name}_vector"] = vec(name)
        arms[f"{name}_hybrid"] = hybrid(name)
    for rr in RERANKERS:
        arms[f"lexical+{rr}"] = reranked(lambda: lex(POOL), rr)
        arms[f"bge-small_hybrid+{rr}"] = reranked(hybrid("bge-small", POOL), rr)
    return arms


def scifact(data: sf.Dataset, only: Sequence[str] | None) -> dict[str, Any]:
    qids = data.judged_queries
    per_query: dict[str, list[float]] = {}
    rows: dict[str, dict[str, float]] = {}
    arms = scifact_arms(data)
    for name, build in arms.items():
        if only and name not in only and name != "lexical":
            continue
        started = time.perf_counter()
        try:
            search = build()
            ranked = {q: search(data.queries[q]) for q in qids}
        except Exception as exc:  # a model that fails to load is reported, not substituted
            missing[name] = f"{type(exc).__name__}: {exc}"[:300]
            print(f"  {name}: MISSING ({missing[name]})", flush=True)
            continue
        scores = [sf.ndcg_at_k(ranked[q], data.qrels[q], K) for q in qids]
        per_query[name] = scores
        rows[name] = {"ndcg_at_10": round(statistics.fmean(scores), 4),
                      "recall_at_10": round(statistics.fmean(
                          sf.recall_at_k(ranked[q], data.qrels[q], K) for q in qids), 4),
                      "seconds": round(time.perf_counter() - started, 1)}
        print(f"  scifact {name}: {rows[name]}", flush=True)
        if name == "lexical":
            check_baseline(rows[name]["ndcg_at_10"])
    oracle = sf.arm_oracle(data, K)
    oracle_scores = [sf.ndcg_at_k(oracle(q), data.qrels[q], K) for q in qids]
    rows["oracle"] = {"ndcg_at_10": round(statistics.fmean(oracle_scores), 4)}
    return {"rows": rows, "per_query": per_query}


def check_baseline(b: float) -> None:
    """8c before any model arm: a baseline at the ceiling means the metric is wrong."""
    if b >= 0.999:
        raise SystemExit("8c: lexical reaches the ceiling on SciFact; the metric is wrong")


def bootstrap_gain(a: Sequence[float], b: Sequence[float], seed: int) -> float:
    rng = random.Random(seed)
    n = len(a)
    idx = [rng.randrange(n) for _ in range(n)]
    return statistics.fmean(a[i] - b[i] for i in idx)


# --- LongMemEval through the product ----------------------------------------

def lme_config(arm: str) -> dict[str, Any] | None:
    base, _, rr = arm.partition("+")
    kwargs: dict[str, Any] = {}
    if base == "lexical":
        kwargs["retrieval"] = "lexical"
    elif base == "hashing_hybrid":
        kwargs["retrieval"] = "hybrid"
    elif base.endswith("_hybrid") and base[:-7] in EMBEDDERS:
        kwargs.update(retrieval="hybrid", embedder=embedder(base[:-7]))
    else:
        return None
    if rr:
        kwargs["rerank"] = reranker(rr)
    return kwargs


def longmemeval(instances: Sequence[Mapping[str, Any]], arms: Sequence[str]) -> dict[str, Any]:
    from memory_fabric import MemoryFabric

    rows: dict[str, dict[str, float]] = {}
    for arm in ["lexical", *[a for a in arms if a != "lexical"], "oracle"]:
        if arm in missing:
            continue
        try:
            config = {} if arm == "oracle" else lme_config(arm)
        except Exception as exc:
            missing[arm] = f"{type(exc).__name__}: {exc}"[:300]
            continue
        if config is None:
            continue
        recalls, latencies = [], []
        for inst in instances:
            gold = {(sid, pos) for sid, session in zip(inst["haystack_session_ids"],
                                                         inst["haystack_sessions"])
                    for pos, turn in enumerate(session) if turn.get("has_answer")}
            fabric = MemoryFabric(":memory:", auto_activate=True, encrypt_content=False,
                                  recognise_copies=False,
                                  **(config or {"retrieval": "lexical"}))
            try:
                emb = (config or {}).get("embedder")
                if emb is not None:
                    emb.warm([f"{t.get('role', 'user')}: {(t.get('content') or '').strip()}"
                              for s in inst["haystack_sessions"] for t in s
                              if (t.get("content") or "").strip()])
                mapping = lme._write_history(fabric, inst)
                as_of = lme.parse_date(inst.get("question_date") or "")
                started = time.perf_counter()
                if arm == "oracle":
                    returned = [m for m, p in mapping.items() if p in gold][:K]
                else:
                    returned = [m.id for m in fabric.retrieve(
                        agent_id="lme", query=inst["question"], k=K, min_relevance=0.0,
                        as_of=as_of).exposed]
                latencies.append((time.perf_counter() - started) * 1000)
            finally:
                fabric.close()
            hits = len({mapping[m] for m in returned if m in mapping} & gold)
            recalls.append(hits / len(gold) if gold else 0.0)
        rows[arm] = {"turn_recall": round(statistics.fmean(recalls), 4),
                     "p50_ms": round(statistics.median(latencies), 1)}
        print(f"  longmemeval {arm}: {rows[arm]}", flush=True)
    return rows


def decide(sci: Mapping[str, Any], lm: Mapping[str, Any]) -> dict[str, Any]:
    rows, pq = sci["rows"], sci["per_query"]
    b = rows["lexical"]["ndcg_at_10"]
    bar = b + 0.25 * (1 - b)
    out: dict[str, Any] = {"B": b, "bar_R3a": round(bar, 4),
                           "baseline_drift": round(abs(b - 0.621), 4)}
    ceiling = rows["oracle"]["ndcg_at_10"]
    out["above_oracle"] = [a for a, r in rows.items() if r["ndcg_at_10"] > ceiling + 1e-9]
    lex_lme = lm.get("lexical", {}).get("turn_recall", 0.0)
    verdicts: dict[str, dict[str, Any]] = {}
    for arm, r in rows.items():
        if arm in ("oracle", "lexical") or arm.endswith("_vector"):
            continue
        gains = [round(bootstrap_gain(pq[arm], pq["lexical"], s), 4) for s in range(1, 6)]
        v: dict[str, Any] = {"ndcg": r["ndcg_at_10"], "gains_vs_lexical": gains}
        v["R3a"] = r["ndcg_at_10"] >= bar and all(g > 0 for g in gains)
        l = lm.get(arm)
        v["lme"] = l
        v["R3b"] = bool(l) and l["turn_recall"] >= lex_lme - 0.02
        v["cost_ok"] = bool(l) and l["p50_ms"] <= 250
        base, _, rr = arm.partition("+")
        if rr:
            base_n = rows.get(base, {}).get("ndcg_at_10")
            if base_n is None:
                v["R3c"] = False
            else:
                need = 0.10 * (1 - base_n)
                g = [bootstrap_gain(pq[arm], pq[base], s) for s in range(1, 6)]
                v["R3c"] = r["ndcg_at_10"] - base_n >= need and all(x > 0 for x in g)
        verdicts[arm] = v
    out["arms"] = verdicts
    ok = [a for a, v in verdicts.items()
          if v["R3a"] and v["R3b"] and v["cost_ok"] and v.get("R3c", True)]
    if not ok or out["above_oracle"] or out["baseline_drift"] > 0.01:
        out["ship"] = None
        return out
    top = max(verdicts[a]["ndcg"] for a in ok)
    near = [a for a in ok if verdicts[a]["ndcg"] >= top - 0.005]
    cost = {"bge-small": 0, "arctic-m": 1, "bge-base": 2, "nomic": 3, "lexical": -1,
            "hashing": -1}
    near.sort(key=lambda a: (cost.get(a.split("_")[0].split("+")[0], 9), "+" in a,
                             -verdicts[a]["ndcg"]))
    out["ship"] = near[0]
    return out


def to_markdown(result: Mapping[str, Any]) -> str:
    d = result["decision"]
    lines = [
        "# R3 — the best retriever this product can ship",
        "",
        "Registered in [r3-best-retriever.md](../prereg/r3-best-retriever.md). Produced by "
        f"`python -m experiments.retriever_eval` at commit `{result['commit']}` in CI "
        f"(run {result.get('run', 'local')}); raw numbers in "
        "[r3-best-retriever.json](r3-best-retriever.json).",
        "",
        f"**Shipped configuration: `{d['ship']}`.** Baseline B = {d['B']:.3f} "
        f"(drift from registration {d['baseline_drift']:.3f}); R3a bar {d['bar_R3a']:.3f}. "
        f"Arms above the oracle: {d['above_oracle'] or 'none'}.",
        "",
        "| arm | SciFact nDCG@10 | R@10 | LongMemEval turn recall | p50 ms | R3a | R3b | R3c | cost |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    rows = result["scifact"]["rows"]
    for arm, r in sorted(rows.items(), key=lambda x: -x[1]["ndcg_at_10"]):
        v = d["arms"].get(arm, {})
        lm = result["longmemeval"].get(arm, {})

        def mark(key: str) -> str:
            return "" if key not in v else ("pass" if v[key] else "fail")
        lines.append(
            f"| `{arm}` | {r['ndcg_at_10']:.3f} | {r.get('recall_at_10', 1.0):.3f} "
            f"| {lm.get('turn_recall', float('nan')):.3f} | {lm.get('p50_ms', '')} "
            f"| {mark('R3a')} | {mark('R3b')} | {mark('R3c')} | {mark('cost_ok')} |")
    if result["missing"]:
        lines += ["", "Missing (failed to load, not substituted):", ""]
        lines += [f"- `{a}`: {why}" for a, why in result["missing"].items()]
    return "\n".join(lines) + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--lme-limit", type=int, default=60)
    p.add_argument("--arms", nargs="*")
    p.add_argument("--run", default="local")
    args = p.parse_args(argv)
    data = sf.load()
    print("SciFact", flush=True)
    sci = scifact(data, args.arms)
    print("LongMemEval", flush=True)
    lm = longmemeval(lme.load("s", limit=args.lme_limit),
                     [a for a in sci["rows"] if a != "oracle"])
    commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True,
                            text=True, cwd=ROOT).stdout.strip()
    result = {"commit": commit, "run": args.run, "scifact": sci, "longmemeval": lm,
              "missing": missing, "decision": decide(sci, lm)}
    out = ROOT / "research" / "results"
    slim = {**result, "scifact": {"rows": sci["rows"]}}
    (out / "r3-best-retriever.json").write_text(json.dumps(slim, indent=2) + "\n")
    (out / "r3-best-retriever.md").write_text(to_markdown(result))
    print("=== R3 JSON ===")
    print(json.dumps(slim))
    print("=== R3 END ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
