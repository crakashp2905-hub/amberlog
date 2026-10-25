# R3 — the best retriever this product can ship

Registered in [r3-best-retriever.md](../prereg/r3-best-retriever.md). Produced by `python -m experiments.retriever_eval` at commit `9d9ef4d` in CI (run 40235543450); raw numbers in [r3-best-retriever.json](r3-best-retriever.json).

**Shipped configuration: `bge-base_hybrid`.** Baseline B = 0.621 (drift from registration 0.000); R3a bar 0.716. Arms above the oracle: none.

| arm | SciFact nDCG@10 | R@10 | LongMemEval turn recall | p50 ms | R3a | R3b | R3c | cost |
|---|---|---|---|---|---|---|---|---|
| `oracle` | 1.000 | 1.000 | 1.000 | 0.1 |  |  |  |  |
| `bge-small_hybrid+jina-turbo` | 0.754 | 0.876 | 0.876 | 3604.9 | pass | pass | fail | fail |
| `bge-base_vector` | 0.746 | 0.867 | — |  |  |  |  |  |
| `bge-base_hybrid` | 0.743 | 0.889 | 0.861 | 45.6 | pass | pass |  | pass |
| `bge-small_hybrid` | 0.734 | 0.871 | 0.797 | 31.8 | pass | pass |  | pass |
| `bge-small_hybrid+bge-rr` | 0.733 | 0.869 | 0.879 | 17895.5 | pass | pass | fail | fail |
| `bge-small_vector` | 0.721 | 0.840 | — |  |  |  |  |  |
| `lexical+jina-turbo` | 0.720 | 0.809 | 0.851 | 3511.4 | pass | pass | pass | fail |
| `lexical+bge-rr` | 0.706 | 0.817 | 0.823 | 17593.1 | fail | pass | pass | fail |
| `bge-small_hybrid+minilm` | 0.703 | 0.843 | 0.858 | 2720.7 | fail | pass | fail | fail |
| `lexical+minilm` | 0.680 | 0.793 | 0.801 | 2651.2 | fail | pass | pass | fail |
| `lexical` | 0.621 | 0.755 | 0.768 | 9.3 |  |  |  |  |
| `hashing_hybrid` | 0.558 | 0.712 | 0.703 | 11.7 | fail | fail |  | pass |
| `arctic-m_hybrid` | 0.526 | 0.703 | 0.810 | 46.0 | fail | pass |  | pass |
| `arctic-m_vector` | 0.118 | 0.182 | — |  |  |  |  |  |

Missing (not measured, not substituted):

- `nomic_vector`: ran out of memory in every job of run 40235543450 (onnxruntime asked for 29 GB on a batch of length-sorted long turns; the SciFact job lost its runner). The model loaded. Fixed after the run (character budget per batch, 1cf1f31); nomic is not measured here.
- `nomic_hybrid`: ran out of memory in every job of run 40235543450 (onnxruntime asked for 29 GB on a batch of length-sorted long turns; the SciFact job lost its runner). The model loaded. Fixed after the run (character budget per batch, 1cf1f31); nomic is not measured here.

## Reading

- **Shipped: `bge-base` fused with lexical, no reranker.** It passes R3a (0.743 against a bar of 0.716,
  positive in all five resamples), R3b (LongMemEval 0.861 against lexical's 0.768) and the cost bound
  (46 ms p50). `bge-small_hybrid` also passes but is 0.010 lower on SciFact, outside the 0.005 tie band.
- **No reranker ships.** Every reranked arm fails the registered 250 ms cost bound on the CI runner
  (2.7–17.9 s a query for a pool of 30). The best of them, `bge-small_hybrid+jina-turbo`, is the top
  SciFact arm (0.754) but adds 0.020 over its base, under R3c's 10%-of-headroom bar (0.027).
- **`arctic-m` is an outlier, not a verdict on the model:** 0.118 alone on SciFact is far below its
  published range, which points to this harness not adding the query instruction that model expects.
  It is reported as measured; nothing was tuned after seeing it.
- **LongMemEval is measured with hostile-source withholding off** (amendment 2). With it on, as
  shipped, a single injection-screen false positive withheld every turn and retrieval returned nothing.
