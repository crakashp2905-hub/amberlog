# R3 — the best retriever this product can ship

Registered in [r3-best-retriever.md](../prereg/r3-best-retriever.md). Produced by `python -m experiments.retriever_eval` at commit `b279848` in CI (run 40401777737 (amendments 3 and 4; other parts from 40235543450)); raw numbers in [r3-best-retriever.json](r3-best-retriever.json).

**Shipped configuration: `bge-base_hybrid`.** Baseline B = 0.621 (drift from registration 0.000); R3a bar 0.716. Arms above the oracle: none.

| arm | SciFact nDCG@10 | R@10 | LongMemEval turn recall | p50 ms | R3a | R3b | R3c | cost |
|---|---|---|---|---|---|---|---|---|
| `oracle` | 1.000 | 1.000 | 1.000 | 0.1 |  |  |  |  |
| `bge-small_hybrid+jina-turbo` | 0.754 | 0.876 | 0.876 | 3604.9 | pass | pass | fail | fail |
| `bge-base_vector` | 0.746 | 0.867 | — |  |  |  |  |  |
| `bge-base_hybrid` | 0.743 | 0.889 | 0.861 | 45.6 | pass | pass |  | pass |
| `nomic_hybrid` | 0.735 | 0.873 | 0.855 | 69.3 | pass | pass |  | pass |
| `bge-small_hybrid` | 0.734 | 0.871 | 0.797 | 31.8 | pass | pass |  | pass |
| `bge-small_hybrid+bge-rr` | 0.733 | 0.869 | 0.879 | 17895.5 | pass | pass | fail | fail |
| `arctic-m_hybrid` | 0.732 | 0.866 | 0.845 | 34.6 | pass | pass |  | pass |
| `arctic-m_vector` | 0.722 | 0.864 | — |  |  |  |  |  |
| `bge-small_vector` | 0.721 | 0.840 | — |  |  |  |  |  |
| `lexical+jina-turbo` | 0.720 | 0.809 | 0.851 | 3511.4 | pass | pass | pass | fail |
| `nomic_vector` | 0.708 | 0.854 | — |  |  |  |  |  |
| `lexical+bge-rr` | 0.706 | 0.817 | 0.823 | 17593.1 | fail | pass | pass | fail |
| `bge-small_hybrid+minilm` | 0.703 | 0.843 | 0.858 | 2720.7 | fail | pass | fail | fail |
| `lexical+minilm` | 0.680 | 0.793 | 0.801 | 2651.2 | fail | pass | pass | fail |
| `lexical` | 0.621 | 0.755 | 0.768 | 9.3 |  |  |  |  |
| `hashing_hybrid` | 0.558 | 0.712 | 0.703 | 11.7 | fail | fail |  | pass |

## Reading

- **Shipped: `bge-base` fused with lexical, no reranker** — unchanged by amendments 3 and 4. It passes
  R3a (0.743 against a bar of 0.716, positive in all five resamples), R3b (LongMemEval 0.861 against
  lexical's 0.768) and the cost bound (46 ms p50).
- **Every embedder family now passes R3a, R3b and the cost bound**, and bge-base leads the next
  (nomic 0.735, bge-small 0.734, arctic-m 0.732) by more than the 0.005 tie band.
- **arctic-m needed its query instruction.** Without it (the first run) it scored 0.118 alone on SciFact;
  with it, 0.722. fastembed adds no prefix; `FastEmbedEmbedder` now adds each model's own.
- **nomic is measured with each text cut to its first 8,000 characters** (amendment 4), a constraint the
  512-token models never reach. Unconstrained, three CI runners ran out of memory on pasted documents.
- **No reranker ships.** Every reranked arm fails the 250 ms cost bound on a CPU runner (2.7–17.9 s a
  query for a pool of 30); the best, `bge-small_hybrid+jina-turbo`, also adds under R3c's bar.
- **LongMemEval is measured with hostile-source withholding off** (amendment 2). Since S1 the default
  costs 0.003 (`longmemeval.md`).
