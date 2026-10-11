# SciFact — the external benchmark, and what my own one was hiding

**The hashing embedder is not slightly worse than lexical retrieval. It is
less than half as good.** On a real corpus with third-party labels it scores
**0.315 nDCG@10 against lexical's 0.621** — and `relevance_v1` reported that
same comparison as 0.728 against 0.790, an 8% gap rather than a 2× one.

My own benchmark understated the problem by a wide margin, and only an external
one could show it.

- **Dataset:** SciFact (BEIR / MTEB), 5,183 biomedical abstracts, **300 judged queries, 339 relevance judgements** made by the SciFact authors years before this project existed
- **Run:** 2026-10-11, `python -m experiments.external_bench`, full corpus, k=10
- **Deterministic:** no model calls in these four arms; two runs of one commit agree exactly

---

## 1. The numbers

| arm | nDCG@10 | Recall@10 | MRR |
|---|---|---|---|
| **`lexical`** (IDF overlap) | **0.621** | 0.755 | 0.585 |
| `hashing_hybrid` (the shipped default) | 0.558 | 0.712 | 0.516 |
| `hashing_vector` | 0.315 | 0.412 | 0.290 |
| `oracle` | 1.000 | 1.000 | 1.000 |

The ceiling held: no arm beat the oracle (principle 8b).

## 2. A credibility anchor the internal benchmark cannot provide

Published BM25 on SciFact is around **0.665 nDCG@10**. The `lexical` arm here
is deliberately parameter-free — length-normalised IDF overlap, no `k1`, no
`b`, because tuning those on a dev split before a ranker milestone exists is
how a baseline quietly becomes a fitted model — and it lands at **0.621**,
a little under properly-tuned BM25.

That is the right place for it to land, and it is worth more than any number in
`relevance_v1`: it says the harness, the metrics and the arm are all behaving
the way a third party would expect. A lexical arm scoring 0.9 here would have
meant the metric was wrong.

## 3. What `relevance_v1` was hiding, and why

| comparison | `relevance_v1` dev | SciFact |
|---|---|---|
| lexical | 0.790 | 0.621 |
| hashing vector | 0.728 | **0.315** |
| gap | 0.062 | **0.306** |

Three reasons the internal benchmark flattered the hashing embedder, all of
them properties I built into it:

1. **18–20 memories per case.** A hashed bag-of-words can rank 20 short facts tolerably; it cannot rank 5,183 abstracts. The corpus size that made `relevance_v1` discriminating at all is still far too small to stress an embedder.
2. **My distractors.** I wrote them to be on-topic but clearly wrong — depot facts against equipment questions. Real distractors are near-misses in the same technical register, which is exactly where hashed tokens fail.
3. **Short, literal memories.** A single sentence shares most of its tokens with a question about it. An abstract paraphrases, and hashing has no notion of paraphrase.

None of this makes `relevance_v1` useless — it tests provenance, retraction,
tenancy and temporal validity, none of which SciFact has. It makes it unsuitable
as the *only* benchmark, which is the case for having both.

## 4. The shipped default is wrong on a real corpus

`hybrid` — reciprocal-rank fusion of the hashing embedder with lexical — is the
default, chosen in R1 because it beat vector-only and had better
critical-memory omission on `relevance_v1`.

On SciFact it scores **0.558 against lexical's 0.621**: fusing the weak arm
**costs 6.3 points**. And this is not an isolated reading — on `relevance_v1`'s
own expanded test split, `lexical` scores 0.733 against the shipped `current`
arm's 0.693. **Lexical beats the default on the held-out split of both
benchmarks.**

RRF is the mechanism: it is rank-based and therefore scale-free, which is why
it was chosen, but it also means a consistently bad arm contributes rank votes
that a good arm has to outweigh. With a hashed embedder those votes are close
to noise, and noise with a vote is worse than no vote.

**So the default changes to `lexical`**, with `hybrid` available and
recommended *when a trained embedder is configured*, where fusion did help on
`relevance_v1`'s test split (0.849 against 0.802). The rule is not "fusion is
bad" but "do not fuse a weak arm into a strong one".

### The decision was not clean, and the splits disagreed

Having changed a product default, the full comparison belongs here rather than
only the number that supported it.

| arm | dev nDCG | dev crit. omission | test nDCG | test crit. omission |
|---|---|---|---|---|
| `lexical` | 0.790 | 0.250 | **0.733** | 0.263 |
| `lexical` + mechanisms (**the new default**) | **0.796** | 0.214 | 0.720 | 0.263 |
| `hybrid` | 0.757 | 0.214 | 0.686 | **0.158** |
| `hybrid` + mechanisms | 0.799 | **0.143** | 0.713 | 0.210 |

On `relevance_v1` alone this does not resolve: dev prefers hybrid+mechanisms on
both metrics, test prefers lexical on nDCG and plain hybrid on critical
omission. Four arms within 0.04 of each other on 20 and 30 cases is not a
ranking.

**SciFact broke the tie**, and it should: 300 queries, 5,183 documents, labels
written by someone else, and a 6.3-point margin with no ambiguity. The argument
for weighting it is the one this document is about — hybrid's critical-omission
advantage appears only on the benchmark whose corpora are small enough to
flatter a hashed embedder, which is the same flattery §3 just quantified.

A reader who weights critical omission above everything and distrusts external
corpora should set `retrieval="hybrid"`. The numbers are here to make that
choice rather than to foreclose it.

**The mechanisms stay on by default** at −0.013 on the test split and +0.006 on
dev, which is to say measurably nothing either way on this benchmark — kept
because they address indirect evidence and copied sources, which SciFact cannot
test at all, and because R6 measured them at **+0.076 downstream correctness**
([R6](r6-downstream.md) §4).

## 5. What this does not establish

1. **No trained-embedder number here yet.** `real_vector` and `real_hybrid` need 5,183 embeddings and the run collided with R6 for a CPU-bound model server; it is queued, not abandoned, and this document will be amended with the result rather than quietly completed.
2. **SciFact is not this project's domain.** No provenance, no lifecycle, no retraction, no tenants. The governance layer is inert and the R4/R5 mechanisms have nothing to act on. It measures retrieval on a hard real corpus.
3. **One external dataset.** SciFact is scientific claim verification; a different BEIR task could order the arms differently, and BEIR exists precisely because single-dataset results mislead.
4. **k=10, the BEIR convention**, not the k=3 `relevance_v1` uses. The arms are compared to each other at the same k, but the two benchmarks' absolute numbers are not comparable.

## 6. The honest summary

> An external benchmark with labels I did not write showed the hashing embedder
> scoring **less than half** of plain lexical retrieval — 0.315 against 0.621 —
> where my own benchmark had reported an 8% gap. The internal benchmark was
> flattering it, through corpus size, distractors I chose, and memories short
> enough that token overlap nearly always works.
>
> The parameter-free lexical arm landing just under published BM25 is the most
> reassuring number in this project: it says the harness and the metrics behave
> the way a third party would expect.
>
> And it changes the product. The shipped `hybrid` default **loses to lexical
> alone on the held-out split of both benchmarks**, because reciprocal-rank
> fusion gives a near-noise arm real votes. The default becomes `lexical`;
> fusion stays, recommended where a trained embedder makes both arms worth
> fusing.
