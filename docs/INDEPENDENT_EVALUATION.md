# Independent evaluation: what exists, and what does not

"Independent" has three meanings here, and the project meets only the first
two. Every result, failures included, is in
[research/SCORECARD.md](../research/SCORECARD.md).

## 1. Third-party data, our harness

Benchmarks with labels written by other people, before this project existed:

| benchmark | what it measured | headline | result file |
|---|---|---|---|
| **LongMemEval** (Wu et al., ICLR 2025): 500 questions, gold evidence by the authors | retrieval over long conversational histories, including knowledge updates | lexical turn recall 0.753 at k = 10; the fabric almost never abstains | [longmemeval.md](../research/results/longmemeval.md) |
| **SciFact** (BEIR): 5,183 abstracts, 300 judged queries | retrieval quality on real text | lexical 0.621 nDCG@10, hashing embedder 0.315, trained hybrid 0.726 (above published BM25) | [scifact-external.md](../research/results/scifact-external.md) |

Both are **retrieval-stage** measurements. Neither is comparable with
published end-to-end QA accuracy.

## 2. Our scenarios, kept independent of the mechanism's design

- **Pre-registered** before any test seed ran: hypothesis, metric,
  threshold, oracle and baselines (`research/prereg/`).
- **Held-out seeds**, never used while designing the mechanism.
- **Fair baselines**, measured in the same run, on the same metric
  (AGENTS.md 8a–8d).
- **Failures published**, with the same prominence as passes:

| result | outcome |
|---|---|
| G4 | not supported |
| S1 | abandoned |
| S2 | not supported |
| T1 | not supported |
| T2 | not supported |
| M2a | not supported |
| G4b | not supported at its bar |

- **Real local models** (qwen2.5:3b, gemma3:4b) wherever a model is in the loop.

LabNet, ObjectiveWorld and the other worlds are independent of the earlier
benchmarks' templates, but **not of their author**. A mechanism designed by the
same project that wrote the scenario can fit it without anyone intending to.

## 3. Independent evaluators: none yet

No third party has reproduced any result, audited the code, or red-teamed the
system. This is the project's largest evidence gap, and the roadmap's Phase 6.
To make reproduction possible:

- every result names its command, commit and seeds;
- deterministic harnesses reproduce exactly;
- model-backed harnesses cache answers by prompt hash, so a rerun with the
  same model reproduces the registered numbers;
- the release record ties each claim to the exact tagged commit
  ([RELEASE_EVALUATION.md](RELEASE_EVALUATION.md)).
