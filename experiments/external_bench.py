"""SciFact (BEIR/MTEB) — an external benchmark with labels I did not write.

`relevance_v1` has one honest weakness that no amount of extra cases fixes: I
wrote the corpus, the queries and the labels. Its result is "this retriever
does well on a world its author built". SciFact is the opposite in every way
that matters here:

* **Third-party relevance judgements.** 339 query–document pairs from the BEIR benchmark, annotated by the SciFact authors for a scientific-claim verification task, years before this project existed. Nothing about them was chosen to flatter anything here.
* **A real corpus.** 5,183 biomedical abstracts, not 20 handwritten facts with distractors I invented.
* **Standard metrics.** nDCG@10 is the number BEIR papers report, so the figures here are comparable to published work rather than only to each other.

What it is **not**: a test of anything this project is actually about. SciFact
has no provenance, no lifecycle, no tenants, no retraction and no temporal
validity, so the governance layer is inert and the three mechanisms R4/R5 added
have nothing to act on. It measures *retrieval quality on a hard real corpus*
and nothing else. Both benchmarks are needed and neither substitutes.

## Data

`research/bench/external/scifact-raw/`, fetched once from
`huggingface.co/datasets/mteb/scifact` (the plain-JSONL mirror; the canonical
BEIR host serves a broken certificate chain). Not committed — 8 MB of someone
else's data — and `fetch()` re-downloads it on demand.

Treated as untrusted input: parsed with the stdlib, never executed, and every
record validated before use.
"""

from __future__ import annotations

import argparse
import json
import math
import pathlib
import sys
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Mapping, Sequence

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from memory_fabric.vectors import (  # noqa: E402
    HashingEmbedder,
    LexicalIndex,
    VectorIndex,
    fuse,
)

RAW = pathlib.Path(__file__).resolve().parent.parent / "research" / "bench" / "external" / "scifact-raw"
SOURCE = "https://huggingface.co/datasets/mteb/scifact/resolve/main/"
FILES = {"corpus.jsonl": "corpus.jsonl", "queries.jsonl": "queries.jsonl",
         "qrels_test.tsv": "qrels/test.tsv"}
DEFAULT_K = 10


def fetch(force: bool = False) -> pathlib.Path:
    """Download the dataset if it is not already present."""
    RAW.mkdir(parents=True, exist_ok=True)
    for local, remote in FILES.items():
        target = RAW / local
        if target.exists() and not force:
            continue
        with urllib.request.urlopen(SOURCE + remote, timeout=180) as response:
            target.write_bytes(response.read())
    return RAW


@dataclass
class Dataset:
    corpus: dict[str, str]
    queries: dict[str, str]
    qrels: dict[str, dict[str, int]]

    @property
    def judged_queries(self) -> list[str]:
        """Only queries with judgements.

        SciFact ships 1,109 queries and 339 test judgements. Scoring the
        unjudged ones would divide by a relevant set that does not exist and
        quietly drag every arm toward zero — a bug that makes every method look
        equally bad, which is the kind that survives review.
        """
        return sorted(q for q in self.qrels if q in self.queries)


def load(limit_corpus: int | None = None) -> Dataset:
    if not (RAW / "corpus.jsonl").exists():
        fetch()

    corpus: dict[str, str] = {}
    for line in (RAW / "corpus.jsonl").read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        identifier = str(record.get("_id", ""))
        if not identifier:
            continue
        title = str(record.get("title") or "")
        text = str(record.get("text") or "")
        corpus[identifier] = f"{title}. {text}".strip()

    queries: dict[str, str] = {}
    for line in (RAW / "queries.jsonl").read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        identifier = str(record.get("_id", ""))
        if identifier:
            queries[identifier] = str(record.get("text") or "")

    qrels: dict[str, dict[str, int]] = {}
    rows = (RAW / "qrels_test.tsv").read_text(encoding="utf-8").splitlines()
    for row in rows[1:]:  # the first row is a header
        parts = row.split("\t")
        if len(parts) < 3:
            continue
        query_id, doc_id, score = parts[0].strip(), parts[1].strip(), parts[2].strip()
        try:
            relevance = int(score)
        except ValueError:
            continue
        if relevance > 0:
            qrels.setdefault(query_id, {})[doc_id] = relevance

    if limit_corpus is not None:
        # A deterministic subset: every judged document, plus enough others to
        # reach the limit. Keeping the judged documents is not optional — a
        # subset that dropped them would measure a corpus the labels are not
        # about.
        needed = {d for judgements in qrels.values() for d in judgements}
        keep = {d: corpus[d] for d in sorted(needed) if d in corpus}
        for doc_id in sorted(corpus):
            if len(keep) >= limit_corpus:
                break
            keep.setdefault(doc_id, corpus[doc_id])
        corpus = keep

    return Dataset(corpus=corpus, queries=queries, qrels=qrels)


# --- arms -------------------------------------------------------------------
#
# Indexes are built once per arm over the whole corpus, not per query: 5,183
# documents embedded 300 times would be the benchmark measuring its own
# harness.


def _lexical_index(dataset: Dataset) -> LexicalIndex:
    index = LexicalIndex()
    for doc_id, text in dataset.corpus.items():
        index.add(doc_id, text)
    return index


def _vector_index(dataset: Dataset, embedder: Any) -> VectorIndex:
    index = VectorIndex(embedder)
    warm = getattr(embedder, "warm", None)
    if warm is not None:
        # One batched request beats 5,183 round trips.
        warm(list(dataset.corpus.values()))
    for doc_id, text in dataset.corpus.items():
        index.add(doc_id, text)
    return index


def arm_lexical(dataset: Dataset, k: int):
    index = _lexical_index(dataset)
    return lambda query: [d for d, _ in index.search(query, k=k, min_relevance=0.0)]


def arm_hashing_vector(dataset: Dataset, k: int):
    index = _vector_index(dataset, HashingEmbedder())
    return lambda query: [d for d, _ in index.search(query, k=k, min_relevance=0.0)]


def arm_hashing_hybrid(dataset: Dataset, k: int):
    lexical = _lexical_index(dataset)
    vector = _vector_index(dataset, HashingEmbedder())
    return lambda query: [
        d
        for d, _ in fuse(
            vector.search(query, k=k, min_relevance=0.0),
            lexical.search(query, k=k, min_relevance=0.0),
            k=k,
        )
    ]


_SHARED_EMBEDDER = None


def _real_embedder():
    """One embedder for every arm that needs it.

    Shared because `real_vector` and `real_hybrid` index the same 5,183
    documents: a fresh embedder per arm meant embedding the corpus twice, which
    doubled a 25-minute run for nothing. The same mistake the relevance
    benchmark made and fixed.
    """
    global _SHARED_EMBEDDER
    if _SHARED_EMBEDDER is not None:
        return _SHARED_EMBEDDER
    from memory_fabric.adapters.ollama import OllamaClient, OllamaEmbedder

    client = OllamaClient()
    model = client.resolve("nomic-embed-text", client.available())
    if model is None:
        raise RuntimeError("nomic-embed-text is not installed")
    _SHARED_EMBEDDER = OllamaEmbedder(client=client, model=model)
    return _SHARED_EMBEDDER


def arm_real_vector(dataset: Dataset, k: int):
    index = _vector_index(dataset, _real_embedder())
    return lambda query: [d for d, _ in index.search(query, k=k, min_relevance=0.0)]


def arm_real_hybrid(dataset: Dataset, k: int):
    lexical = _lexical_index(dataset)
    vector = _vector_index(dataset, _real_embedder())
    return lambda query: [
        d
        for d, _ in fuse(
            vector.search(query, k=k, min_relevance=0.0),
            lexical.search(query, k=k, min_relevance=0.0),
            k=k,
        )
    ]


def arm_oracle(dataset: Dataset, k: int):
    """The judged documents, in judgement order. The ceiling (principle 8b).

    Same `k`, same corpus, differing only in knowing the answer. It reaches
    1.000 here because SciFact has no gates to refuse anything — unlike
    `relevance_v1`, where the oracle is bounded by the same authorisation and
    lifecycle filters as every arm.
    """
    def run(query_id_or_text: str, _dataset=dataset):
        judged = _dataset.qrels.get(query_id_or_text, {})
        return sorted(judged, key=lambda d: (-judged[d], d))[:k]

    return run


ARMS: dict[str, Callable[[Dataset, int], Any]] = {
    "lexical": arm_lexical,
    "hashing_vector": arm_hashing_vector,
    "hashing_hybrid": arm_hashing_hybrid,
    "real_vector": arm_real_vector,
    "real_hybrid": arm_real_hybrid,
}
BY_QUERY_ID = {"oracle"}
CEILING = "oracle"


# --- metrics ----------------------------------------------------------------


def ndcg_at_k(ranked: Sequence[str], judged: Mapping[str, int], k: int) -> float:
    gains = [judged.get(doc_id, 0) for doc_id in ranked[:k]]
    actual = sum(g / math.log2(i + 2) for i, g in enumerate(gains))
    ideal_gains = sorted(judged.values(), reverse=True)[:k]
    ideal = sum(g / math.log2(i + 2) for i, g in enumerate(ideal_gains))
    return (actual / ideal) if ideal > 0 else 0.0


def recall_at_k(ranked: Sequence[str], judged: Mapping[str, int], k: int) -> float:
    if not judged:
        return 0.0
    found = len([d for d in ranked[:k] if d in judged])
    return found / len(judged)


def reciprocal_rank(ranked: Sequence[str], judged: Mapping[str, int]) -> float:
    for position, doc_id in enumerate(ranked):
        if doc_id in judged:
            return 1.0 / (position + 1)
    return 0.0


def evaluate(
    dataset: Dataset, arms: Sequence[str], k: int = DEFAULT_K
) -> dict[str, Any]:
    query_ids = dataset.judged_queries
    results: dict[str, dict[str, float]] = {}
    for name in arms:
        if name == CEILING:
            search = arm_oracle(dataset, k)
            inputs = {q: q for q in query_ids}
        else:
            search = ARMS[name](dataset, k)
            inputs = {q: dataset.queries[q] for q in query_ids}

        ndcgs, recalls, rrs = [], [], []
        for query_id in query_ids:
            ranked = search(inputs[query_id])
            judged = dataset.qrels[query_id]
            ndcgs.append(ndcg_at_k(ranked, judged, k))
            recalls.append(recall_at_k(ranked, judged, k))
            rrs.append(reciprocal_rank(ranked, judged))
        results[name] = {
            f"ndcg_at_{k}": round(sum(ndcgs) / len(ndcgs), 4),
            f"recall_at_{k}": round(sum(recalls) / len(recalls), 4),
            "mrr": round(sum(rrs) / len(rrs), 4),
        }
    return {
        "benchmark": "scifact",
        "source": "BEIR / MTEB, third-party judgements",
        "queries": len(query_ids),
        "documents": len(dataset.corpus),
        "judgements": sum(len(v) for v in dataset.qrels.values()),
        "k": k,
        "arms": results,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--arms", nargs="*", default=["lexical", "hashing_vector",
                                                      "hashing_hybrid", "oracle"],
                        choices=list(ARMS) + [CEILING])
    parser.add_argument("--k", type=int, default=DEFAULT_K)
    parser.add_argument("--limit-corpus", type=int, default=None,
                        help="subset the corpus, keeping every judged document")
    parser.add_argument("--fetch", action="store_true", help="re-download first")
    parser.add_argument("--json", dest="as_json", action="store_true")
    args = parser.parse_args(argv)

    if args.fetch:
        fetch(force=True)
    dataset = load(limit_corpus=args.limit_corpus)
    result = evaluate(dataset, args.arms, k=args.k)

    if args.as_json:
        print(json.dumps(result, indent=2))
        return 0

    print(f"# SciFact — {result['queries']} judged queries, "
          f"{result['documents']} documents, k={result['k']}")
    print(f"# {result['source']}")
    print()
    print(f"| arm | nDCG@{args.k} | Recall@{args.k} | MRR |")
    print("|---|---|---|---|")
    for name, row in result["arms"].items():
        print(f"| `{name}` | {row[f'ndcg_at_{args.k}']:.3f} | "
              f"{row[f'recall_at_{args.k}']:.3f} | {row['mrr']:.3f} |")

    if CEILING in result["arms"]:
        from experiments.stats import report_ceiling

        print()
        scores = {n: r[f"ndcg_at_{args.k}"] for n, r in result["arms"].items()}
        if not report_ceiling(scores, CEILING):
            return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
