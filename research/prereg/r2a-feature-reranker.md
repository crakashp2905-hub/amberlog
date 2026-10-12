
# Pre-registration — R2a: a reranking stage, to make fusion safe

**Registered 2026-10-12, before `memory_fabric/rerank.py` exists.**

## 1. The claim, and why it is not "a better ranker"

This project has measured the same thing five times: **do not fuse a weak arm
into a strong one.** SciFact — fusing a hashed vector arm into lexical costs
6.3 points, and with a trained embedder gains 2.5. `facet_v1` — fusion drags a
strong vector arm down to a weak lexical one. And the cleanest version,
[LongMemEval](../results/longmemeval.md), inside one benchmark:

| haystack | vector | lexical | hybrid | fusion worth |
|---|---|---|---|---|
| 23 turns | 0.820 | 0.817 | **0.851** | +0.034 |
| 491 turns | 0.456 | **0.753** | 0.693 | **−0.060** |

That rule is a **workaround for having no reranker.** Reciprocal-rank fusion
gives every arm equal rank votes and cannot notice that one has gone bad, so
the only available defence is choosing which arms to admit — a decision a
deployment has to make before it knows how its corpus will behave.

So the claim under test is not "reranking retrieves better". It is
**reranking makes fusion safe**: a fused pool reordered by a reranker should
not lose to its own best single arm.

## 2. The mechanism, and what it may not do

`hybrid_reranked` — the existing `hybrid` pool, reordered.

**No model.** A cross-encoder is a call per candidate and lands on the wrong
side of [p4-envelope.md](../results/p4-envelope.md), where retrieval is already
linear beyond a thousand memories. This is a feature-based reranker and its
cost must stay within the same order as the retrieval it reorders.

**No tuned weights**, which is the part most likely to go wrong. Scoring is a
single scale — the share of the query's **IDF mass** a candidate accounts for —
with phrase matches folded in as additional weight rather than added through a
free coefficient, and proximity as a lexicographic tie-break. There is no
combination weight to fit, because a weight fitted on a dev split is how a
baseline quietly becomes a model.

It may use the query, the candidates' content, and corpus statistics the store
already maintains. It may **not** use labels, question type, or anything a
deployment would not have at query time. A test asserts the module names no
answer key.

## 3. Primary metric and threshold

**Primary: turn recall on LongMemEval's `s` split**, 500 instances, median 491
turns a history. The external benchmark, not one of mine, and the one where the
fusion penalty is largest.

```
B = hybrid                   = 0.693   (the arm being fixed)
C = oracle                   = 1.000
support iff turn recall(hybrid_reranked) >= B + 0.40 * (C - B) = 0.816
```

**Also required, and this is the actual claim:** `hybrid_reranked >= lexical`
(0.753). A reranker that improves on `hybrid` while still losing to the better
single arm has not made fusion safe, and the registered bar at 0.816 is
deliberately stricter than that so a pass means both.

**Abandonment clause.** If `C − B <= 0.05`, abandoned rather than
reinterpreted.

**8c check — is the primary trivially maximised by a baseline?** No: `lexical`
0.753, `hybrid` 0.693, `vector` 0.456, all below the 0.816 bar, and `oracle` is
the ceiling rather than a baseline. Run and reported before the comparison, as
principle 8c now requires.

**Ceiling check** every run: an arm above `oracle` means the ceiling is wrong.

## 4. Secondary metrics, reported always, decisive for none

- **The no-regression set**, which matters more here than the primary: `relevance_v2` (dev and test), `facet_v1`, SciFact. A reranker that fixes LongMemEval and breaks SciFact has moved the problem.
- **Does it make fusion safe where fusion already helps?** On LongMemEval's `oracle` split fusion *gains* 3.4 points. `hybrid_reranked` must not lose that.
- `session_recall`, `latency_ms`, candidates reranked.
- `must_not_expose_rate` — any non-zero value fails the run.

## 5. Predictions

1. **It will not reach 0.816.** A feature-based reranker reordering a pool whose weak arm has already pushed good candidates out of the top 10 cannot recover what is absent — reranking reorders, it does not retrieve. I expect it to beat `hybrid` and fall short of the registered bar, and recording that now is the point of registering.
2. **It will pass the secondary claim**, `>= lexical`, because the fused pool contains everything lexical's pool contains. If it fails even that, the features are wrong rather than weak.
3. **The trained-embedder case will gain least.** Where both arms are strong, RRF is already close to right and there is little for a reranker to fix. This is the measurement that would show reranking is specifically a *defence* rather than an improvement.
4. **Rarity-weighted coverage will carry nearly all of it**, with phrase and proximity worth little. Stated so that "the features barely mattered" is a result rather than a disappointment.

## 6. What a pass would not establish

Nothing about a cross-encoder, which is the version Hindsight describes and the
one most likely to work; this registration deliberately tests the cheap version
first. Nothing downstream — whether a better-ordered context changes an answer
is R6's question. And nothing about arm selection: if reranking makes fusion
safe, the right default may still be the single strong arm, because fusion also
costs latency.
