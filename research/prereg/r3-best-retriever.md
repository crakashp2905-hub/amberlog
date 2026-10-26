# Pre-registration — R3: the best retriever this product can ship

**Registered 2026-10-25**, before `experiments/retriever_eval.py` was run on
any arm with a trained model, and before `retrievers.BEST` was set from a
result.

## 1. Question

Which retrieval configuration should `retrievers.best_available()` hand
users? The aim is not a new method. It is to pick, on third-party labels, the
best configuration that installs without PyTorch and runs on a CPU, and to
ship nothing that has not earned its place: a reranker is included only if it
adds measurably over its base.

## 2. Benchmarks

| | role | split | metric | k |
|---|---|---|---|---|
| **SciFact** (BEIR/MTEB) | primary | test, 300 queries, 5,183 documents, 339 judgements | **nDCG@10** | 10 |
| **LongMemEval `s`** | no-regression | 60 instances, stratified by question type (`longmemeval_bench.load(limit=60)`), median ~490 turns | turn recall | 10 |

LongMemEval runs through `MemoryFabric.retrieve`, the product path, with the
harness defaults of `longmemeval_bench` (`as_of` temporal filtering, copy
recognition off). SciFact runs on the indexes directly, as `external_bench`
does. Nothing is tuned on either.

## 3. Baseline, measured where the threshold is written (AGENTS.md 8d)

`lexical` on SciFact, nDCG@10, k=10, test split: **0.621**
(`research/results/scifact-external.md`, same metric, k and split). It is
**re-measured first in the same run**, and the thresholds below use the
re-measured value `B`. The oracle (judged documents, same k) is 1.000, so the
headroom is `1 − B`, about 0.379.

8c check, before any model arm runs: no registered baseline may reach the
oracle. `lexical` at 0.621 and `hashing_hybrid` at 0.558 do not.

## 4. Arms

Embedders, all ONNX through `fastembed`, CPU:
`bge-small` (BAAI/bge-small-en-v1.5, 384-d), `bge-base` (BAAI/bge-base-en-v1.5,
768-d), `arctic-m` (snowflake/snowflake-arctic-embed-m), `nomic` (nomic-ai/nomic-embed-text-v1.5).

Rerankers (cross-encoders, `fastembed`, pool 30): `minilm`
(Xenova/ms-marco-MiniLM-L-6-v2), `bge-rr` (BAAI/bge-reranker-base), `jina-turbo`
(jinaai/jina-reranker-v1-turbo-en).

| arm | what |
|---|---|
| `lexical` | baseline (the shipped default) |
| `hashing_hybrid` | the zero-dependency hybrid |
| `<E>_vector` | each embedder alone |
| `<E>_hybrid` | each embedder fused with lexical (RRF, as shipped) |
| `bge-small_hybrid+<R>` | each reranker over the smallest embedder's hybrid pool |
| `lexical+<R>` | each reranker over lexical: the no-embedder option |
| `oracle` | judged documents, same k |

The same arms run on LongMemEval through the product path, except the
`_vector` arms, which are SciFact-only (they are not a shipping candidate:
fusion is the shipped mode for a trained embedder).

## 5. Thresholds and the decision rule

Five bootstrap resamples of the 300 SciFact queries (seeds 1–5, paired across
arms) give the uncertainty on every gain.

- **R3a (a trained retriever earns its place):** the shipped arm's SciFact
  nDCG@10 is at least `B + 0.25 × (1 − B)` (about 0.716), and its paired gain
  over `lexical` is positive in all five resamples.
- **R3b (no regression where memory is conversational):** the shipped arm's
  LongMemEval turn recall is at least `lexical`'s minus **0.02**.
- **R3c (a reranker earns its place):** a reranked arm may ship only if it
  adds at least **10% of its base's remaining headroom** on SciFact
  (`gain ≥ 0.10 × (1 − base)`), positive in all five resamples, and itself
  passes R3b. Otherwise `BEST["reranker"]` is `None`.
- **Cost bound:** the shipped arm's p50 retrieval latency on LongMemEval,
  through `retrieve`, at most **250 ms** on the CI runner. A slower arm is
  reported and not shipped.

**Which arm ships:** among arms passing R3a, R3b and the cost bound, the one
with the highest SciFact nDCG@10; within 0.005 of it, the cheaper (smaller
embedder, then no reranker). If none passes R3a, `best_available()` keeps
returning `lexical` and the result says so.

**Ceiling check on every run (8b):** an arm above the oracle invalidates the
run.

## 6. What would make this result wrong

- A model that fails to download is reported **missing**, not substituted.
- Published scores for these models are on full BEIR protocols and are not
  comparable to RRF-fused arms; nothing here is compared to them except as a
  sanity range.
- One run on a shared CI runner: latency is indicative, not a benchmark.

## 7. Abandonment

If the re-measured `B` differs from 0.621 by more than 0.01, the harness has
changed under the registration: the run is reported and not used to set
`BEST` until the difference is explained.

## Amendment 1 — procedure only, registered 2026-10-25 before any result

The first run (one CI job, every arm in sequence) was cancelled after about
two hours without producing a result; no number from it was seen. The arms,
benchmarks, metrics, thresholds and decision rule are unchanged. Two changes
to how it runs:

- **Split into five parallel jobs** (`base`, `bge-small`, `bge-base`,
  `arctic-m`, `nomic`), each re-measuring `lexical`; a final job combines them
  and refuses to decide if the parts disagree on the baseline.
- **The vector index scores with numpy when it is installed** (a product
  change: 768-dim scan of 5,000 memories, 212 → 4 ms a query, identical
  rankings to 1e-16). This changes speed, not which documents are returned,
  so the cost bound (p50 ≤ 250 ms) is now measured on the faster index the
  product ships.

## Amendment 2 — procedure only, registered 2026-10-25

Arms, benchmarks, metrics, thresholds and the decision rule are unchanged.

**What was seen first, stated plainly.** Run 40215135822 finished the `base`
part; the four model parts were cancelled at the 4-hour job limit, after
printing SciFact rows for most of their arms (not a complete set, and no
decision was made from them). Every LongMemEval arm, `lexical` included,
scored **0.033** turn recall against an oracle of 1.000, which is a harness
defect rather than a result: a diagnostic run found that `retrieve` returned
nothing at all on these stores. One turn per few hundred trips the write-time
injection screen; the history is written as a single agent, so
`withhold_hostile_sources` (on by default) then withholds every turn. No
LongMemEval number from that run is used.

Changes:

- **`withhold_hostile_sources=False`** in the LongMemEval harness, beside the
  registered `recognise_copies=False` and for the same reason: it would
  measure a write-time screen, not retrieval. The screen's false-positive rate
  on conversational text is reported as a separate finding.
- **SciFact and LongMemEval run as separate jobs**, and LongMemEval's 60
  instances in **three shards** (instances `i::3`), pooled per instance by the
  combine step. Every shard re-measures `lexical` on its own instances and the
  combine step refuses to decide if two families disagree on it.
- **Documents are embedded in order of length** (a product change: a batch is
  padded to its longest text). It changes speed, not vectors.
- Job limit 340 minutes.

## Amendment 3 — procedure only, registered 2026-10-26

Run 40235543450 decided R3 with two families not properly measured, as its
result says: `nomic` ran out of memory in every job, and `arctic-m` was
embedded **without the instruction prefix the model is trained with**
(fastembed adds none; its own model list says the prefix is "necessary"),
scoring 0.118 alone on SciFact. Both are harness defects, not results.

- `FastEmbedEmbedder` now adds each model's documented prefixes
  (`MODEL_PREFIXES`: arctic-m's query instruction, nomic's
  `search_query:`/`search_document:`); `bge` is unchanged, so every arm that
  was measured correctly keeps its numbers.
- **Only the `arctic-m` and `nomic` parts are re-run.** The decision combines
  them with run 40235543450's other parts, and refuses to decide if any shard's
  `lexical` disagrees with that run's.
- Thresholds and the decision rule are unchanged. If either family now passes
  and beats `bge-base_hybrid` by more than the 0.005 tie band, `BEST` changes;
  otherwise it stays. The earlier arctic-m numbers stay in the record, marked
  as measured without the prefix.
