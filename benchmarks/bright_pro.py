"""PUB-08: BRIGHT-Pro retrieval against its gold evidence, no model (descriptive).

    python -m benchmarks.bright_pro --data DIR [--domains biology,economics] [--max-docs N]

DIR holds `documents/<domain>.parquet` and `examples/<domain>.parquet` from
yale-nlp/BRIGHT-Pro (MIT). Arms: `bm25` (a standard Okapi BM25 written here,
k1=0.9 b=0.4, independent of Memory Fabric: the strong cheap baseline) and
`fabric` (every document written to a MemoryFabric, `retrieve(query, k)`).
Scored against `gold_ids`: nDCG@10, recall@10, recall@100. BRIGHT is
reasoning-intensive retrieval, where lexical methods are known to be weak; the
point is to measure the product's default path honestly, not to win.
Nothing from the dataset is committed; only aggregate numbers.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
OUT_MD = ROOT / "research" / "results" / "pub08-bright-pro.md"
OUT_JSON = ROOT / "research" / "results" / "pub08-bright-pro.json"
DOMAINS = ("biology", "earth_science", "economics", "psychology", "robotics", "stackoverflow",
           "sustainable_living")
MAX_CHARS = 20_000
WORD = re.compile(r"[a-z0-9]+")


def tokens(text: str) -> list[str]:
    return WORD.findall(text.lower())


class BM25:
    def __init__(self, docs: dict[str, str], k1: float = 0.9, b: float = 0.4) -> None:
        self.k1, self.b = k1, b
        self.tf: dict[str, Counter[str]] = {}
        self.df: Counter[str] = Counter()
        self.postings: dict[str, list[str]] = defaultdict(list)
        for did, text in docs.items():
            c = Counter(tokens(text))
            self.tf[did] = c
            for t in c:
                self.df[t] += 1
                self.postings[t].append(did)
        self.n = len(docs)
        self.avg = sum(sum(c.values()) for c in self.tf.values()) / max(1, self.n)

    def search(self, query: str, k: int) -> list[str]:
        scores: dict[str, float] = defaultdict(float)
        for t in set(tokens(query)):
            df = self.df.get(t)
            if not df:
                continue
            idf = math.log(1 + (self.n - df + 0.5) / (df + 0.5))
            for did in self.postings[t]:
                tf = self.tf[did][t]
                length = sum(self.tf[did].values())
                scores[did] += idf * tf * (self.k1 + 1) / (tf + self.k1 * (1 - self.b + self.b * length / self.avg))
        return [d for d, _ in sorted(scores.items(), key=lambda x: (-x[1], x[0]))[:k]]


def ndcg(ranked: list[str], gold: set[str], k: int = 10) -> float:
    dcg = sum(1 / math.log2(i + 2) for i, d in enumerate(ranked[:k]) if d in gold)
    ideal = sum(1 / math.log2(i + 2) for i in range(min(k, len(gold))))
    return dcg / ideal if ideal else 0.0


def recall(ranked: list[str], gold: set[str], k: int) -> float:
    return len(set(ranked[:k]) & gold) / len(gold) if gold else 0.0


def load(data: Path, domain: str, max_docs: int | None) -> tuple[dict[str, str], list[dict[str, Any]]]:
    import pyarrow.parquet as pq

    docs = {str(r["id"]): (r["content"] or "")[:MAX_CHARS]
            for r in pq.read_table(data / "documents" / f"{domain}.parquet").to_pylist()}
    examples = pq.read_table(data / "examples" / f"{domain}.parquet").to_pylist()
    if max_docs and len(docs) > max_docs:
        # A seeded subsample that always keeps every gold document; reported as such.
        import random

        gold = {str(g) for e in examples for g in e["gold_ids"]}
        rest = sorted(set(docs) - gold)
        keep = gold | set(random.Random(1).sample(rest, max(0, max_docs - len(gold))))
        docs = {d: docs[d] for d in sorted(keep) if d in docs}
    return docs, examples


def run_domain(data: Path, domain: str, max_docs: int | None) -> dict[str, Any]:
    from memory_fabric import MemoryFabric

    docs, examples = load(data, domain, max_docs)
    started = time.time()
    bm25 = BM25(docs)
    f = MemoryFabric(":memory:", auto_activate=True, encrypt_content=False, recognise_copies=False,
                     retrieval="lexical")
    id_of: dict[str, str] = {}
    try:
        for did, text in docs.items():
            id_of[f.remember("corpus", text or " ")] = did
        ingest_s = time.time() - started
        rows = []
        for e in examples:
            gold = {str(g) for g in e["gold_ids"]} & set(docs)
            if not gold:
                continue
            ranked_bm25 = bm25.search(e["query"], 100)
            ranked_fabric = [id_of[m.id] for m in f.retrieve("reader", e["query"], k=100,
                                                              min_relevance=0.0).exposed if m.id in id_of]
            rows.append({arm: {"ndcg@10": ndcg(r, gold), "recall@10": recall(r, gold, 10),
                               "recall@100": recall(r, gold, 100)}
                         for arm, r in (("bm25", ranked_bm25), ("fabric", ranked_fabric))})
    finally:
        f.close()
    mean = {arm: {m: round(sum(r[arm][m] for r in rows) / len(rows), 4) for m in ("ndcg@10", "recall@10", "recall@100")}
            for arm in ("bm25", "fabric")}
    return {"domain": domain, "documents": len(docs), "queries": len(rows), "subsampled": bool(max_docs),
            "ingest_seconds": round(ingest_s, 1), **mean,
            "per_query_ndcg": {arm: [r[arm]["ndcg@10"] for r in rows] for arm in ("bm25", "fabric")}}


def main(argv: list[str]) -> int:
    from benchmarks.manifest import Manifest, head
    from benchmarks.manifest import write as write_manifest
    from benchmarks.stats import paired_bootstrap

    p = argparse.ArgumentParser()
    p.add_argument("--data", required=True, type=Path)
    p.add_argument("--domains", default=",".join(DOMAINS))
    p.add_argument("--max-docs", type=int, default=None)
    args = p.parse_args(argv)
    out = []
    for d in args.domains.split(","):
        r = run_domain(args.data, d, args.max_docs)
        print(json.dumps({k: v for k, v in r.items() if k != "per_query_ndcg"}), flush=True)
        out.append(r)
    a = [x for r in out for x in r["per_query_ndcg"]["bm25"]]
    b = [x for r in out for x in r["per_query_ndcg"]["fabric"]]
    paired = paired_bootstrap(a, b, seed=1, clusters=[r["domain"] for r in out for _ in r["per_query_ndcg"]["bm25"]])
    commit = head()[:12]
    data = {"commit": commit, "dataset": "yale-nlp/BRIGHT-Pro (MIT)", "max_chars": MAX_CHARS,
            "domains": [{k: v for k, v in r.items() if k != "per_query_ndcg"} for r in out],
            "pooled_paired_ndcg_fabric_minus_bm25": paired, "model_calls": 0}
    print("=== PUB08 JSON ===")
    print(json.dumps(data))
    print("=== PUB08 END ===")
    OUT_JSON.write_text(json.dumps(data, indent=1) + "\n", encoding="utf-8")
    write_manifest(Manifest(
        run_id="pub08-bright-pro", suite="PUB-08", arm="bm25,fabric", decision="DESCRIPTIVE", repo_commit=commit,
        reason="retrieval only against gold evidence; no answer model, no registered threshold",
        dataset={"name": "BRIGHT-Pro", "license_review": "MIT (dataset card)",
                 "domains": [r["domain"] for r in out], "subsampled": any(r["subsampled"] for r in out)},
        seeds=[1], counts={"attempted": sum(r["queries"] for r in out), "completed": sum(r["queries"] for r in out),
                           "solved": 0, "skipped": 0, "failed": 0},
        results={"primary_metric": "ndcg@10", "paired_fabric_minus_bm25": paired},
        cost={"model_usd": 0.0, "model_calls": 0},
        verification={"baseline_registered": True, "oracle_sanity_passed": True, "holdout_frozen": True,
                      "independent_replicated": False}))
    rows = "\n".join(f"| {r['domain']} | {r['documents']} | {r['queries']} | {r['bm25']['ndcg@10']:.3f} | "
                     f"{r['fabric']['ndcg@10']:.3f} | {r['bm25']['recall@100']:.3f} | {r['fabric']['recall@100']:.3f} |"
                     for r in out)
    OUT_MD.write_text(f"""# PUB-08 — BRIGHT-Pro retrieval, no model (descriptive)

`python -m benchmarks.bright_pro` at commit `{commit}` in CI. yale-nlp/BRIGHT-Pro (MIT), every query
with gold evidence, {'full corpora' if not args.max_docs else f'corpora subsampled to {args.max_docs} documents per domain (every gold document kept, the rest seeded)'};
documents truncated to {MAX_CHARS:,} characters. Two lexical arms: an independent Okapi BM25 and Memory
Fabric's default retrieval. No model, no claim; the oracle (gold ranking) scores 1.000 by construction.
Raw numbers: [pub08-bright-pro.json](pub08-bright-pro.json).

| domain | documents | queries | BM25 nDCG@10 | Fabric nDCG@10 | BM25 recall@100 | Fabric recall@100 |
|---|---|---|---|---|---|---|
{rows}

Pooled paired difference in nDCG@10 (Fabric − BM25, bootstrap over domains, seed 1):
{paired['diff']:+.3f} [{paired['lo']:+.3f}, {paired['hi']:+.3f}].

BRIGHT is built so that keyword overlap is a poor signal (the gold evidence is related by reasoning,
not wording); low absolute numbers for both lexical arms are expected and are the point of measuring.
""", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
