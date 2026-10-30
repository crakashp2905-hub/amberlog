# R2a — a feature reranker: it does make fusion safe, and that is not worth having

**NOT SUPPORTED on the registered primary, and the reason is more useful than
the verdict: reranking converges both arms to a roughly fixed quality level set
by the corpus.** That is literally "making fusion safe" — the choice of arm
stops mattering — and it is only a *gain* when the better arm happens to be
worse than that level.

Measured on four benchmarks, and the direction is predictable from one number:

| benchmark | better arm | worse arm | both, reranked | reranking the better arm |
|---|---|---|---|---|
| `relevance_v2` dev | **0.807** | 0.545 | 0.752 | **−0.055** |
| `relevance_v2` test | 0.652 | 0.499 | 0.717 / 0.726 | **+0.065** |
| SciFact | **0.621** | 0.558 | 0.559 / 0.551 | **−0.062** |
| LongMemEval `s` (500) | **0.753** | 0.693 | 0.707 / 0.717 | **−0.046** |
| `facet_v1` | 0.250 | — | 0.250 | 0.000 |

Where the better arm is above the convergence point, reranking costs. Where it
is below, reranking gains. The two splits of one benchmark **disagree in
direction**, which is the usual sign that an effect is inside the noise of 33
cases.

- **Registration:** [r2a-feature-reranker.md](../prereg/r2a-feature-reranker.md), written before `memory-fabric/rerank.py` existed
- **Runs:** 2026-10-12. Deterministic; no model calls
- **Off by default.** A mechanism that misses its registered bar does not become a default

---

## 1. The claim, and why it was worth testing

Five measurements said *do not fuse a weak arm into a strong one*, and that rule
is a workaround for having no reranker: reciprocal-rank fusion gives every arm
equal rank votes by design — it is scale-free, which is why it was chosen — and
so cannot notice that an arm has gone bad. The registered claim was therefore
not "this retrieves better" but **"this makes fusion safe"**.

## 2. It does make fusion safe, and that is the problem

On every benchmark the two reranked arms land within a few points of each
other: 0.752 and 0.752 on `relevance_v2` dev, 0.717 and 0.726 on its test
split, 0.559 and 0.551 on SciFact, and **0.707 and 0.717 on LongMemEval's full
500**. Which arm fed the pool stops mattering, within a point, on every
benchmark — which is exactly what was asked for.

But the convergence point is a property of the reranker, not of the input. It
is roughly "what a rarity-weighted coverage score achieves on this corpus", and
on three of four benchmarks that is **below** the better single arm. So the
mechanism removes a risk by capping the upside, and a caller who already knows
which arm is strong is better off using it.

## 3. The two modes, and why one does literally nothing

| mode | what it does | result |
|---|---|---|
| `replace` | order by coverage alone | the convergence above |
| `tiebreak` | retriever's score first, then phrase order and proximity | **no change at all, on any benchmark** |

`tiebreak` was the design I expected to work: keep the retriever's score and
add the two features it does not have. It changes **nothing** — identical to
the base arm to three decimals on `relevance_v2` (0.807), `facet_v1` (0.250),
and on LongMemEval's full 500 instances (**0.693 against 0.693**) — because
ties on a float score essentially never occur, so the tie-break never fires.

**Prediction 4 is confirmed decisively**: rarity-weighted coverage carries all
of it and phrase order and proximity are worth exactly zero. Recorded in
advance so that "the features barely mattered" is a result rather than a
disappointment — and it is a stronger result than expected, because *zero* is
not *little*.

## 4. Why a feature reranker cannot win here

`LexicalIndex` already scores with **length-normalised IDF**. The reranker's
features are a strict subset of that plus two that never fire, so `replace`
substitutes a weaker scorer for a stronger one and `tiebreak` substitutes
nothing.

This was visible as a bug before it was understood as a limit. The first
version used **unnormalised** coverage and took `lexical` from 0.768 to 0.679
on a 60-instance sample of LongMemEval while *gaining* 0.174 on
`relevance_v2` — because
v2's memories are uniform short facts and a chat turn is not, so a long
rambling turn matches more query words by chance and wins on recall alone.
Balancing recall against precision with a harmonic mean (no free parameter)
fixed that failure and revealed the general one.

**So reranking needs information the retriever lacks**, and for a text
retriever that means a model. A cross-encoder scores the query and candidate
jointly and can tell a well-ranked bad candidate from a good one, which no
combination of surface features can. That is the version
[Hindsight](../HINDSIGHT.md) describes, and this registration deliberately
tested the cheap one first so a win could be attributed to reranking rather
than to a bigger model. The cheap one is not merely weaker; it is structurally
incapable.

## 5. The registered verdict

Primary: turn recall on LongMemEval's `s` split, 500 instances.

```
B = hybrid       = 0.693
C = oracle       = 1.000
threshold          B + 0.40 x headroom = 0.816
also required      hybrid_reranked >= lexical (0.753)
```

`hybrid_replace` reaches **0.717** — above `hybrid` and below `lexical`.
**NOT SUPPORTED**: it closes **7.8%** of the headroom against a registered 40%,
and it fails the secondary claim too.

| prediction | outcome |
|---|---|
| 1. will not reach 0.816 | **right** — 0.717, 7.8% of the headroom |
| 2. will pass `>= lexical` | **wrong** — 0.717 against 0.753 |
| 3. the trained-embedder case will gain least | not run; see §7 |
| 4. coverage carries nearly all of it, phrase and proximity little | **right, and understated** — they are worth zero |

Prediction 2 was the actual claim, and it is the one that failed.

## 6. What survives

Two things worth keeping out of a failed mechanism.

**The convergence itself is a measurement about fusion**, not about the
reranker. It says the fused pool contains what the better arm's pool contains —
otherwise reranking it could not reach the better arm's neighbourhood — so
fusion's damage is entirely in the *ordering*, not in the candidate set. That
is a sharper statement of the fusion rule than five previous measurements
produced, and it is what makes a cross-encoder the right next thing rather than
a speculative one.

**`relevance_v2`'s splits disagree** (−0.055 dev, +0.065 test). Over 33 cases
with four arms inside 0.3 of each other, that is noise, and it is a standing
reminder that this benchmark cannot separate close arms — the same conclusion
R2 is blocked on.

## 7. What this does not establish

1. **Nothing about a cross-encoder**, the version most likely to work. §4 is an argument for it, not evidence about it.
2. **No trained-embedder arm.** Prediction 3 — that reranking gains least where both arms are strong — is untested, because LongMemEval's `s` split needs ~245,000 embeddings for 500 instances at ~491 turns each, roughly 47× the SciFact corpus. A stratified subset is the tractable version and is the next measurement rather than a result.
3. **Four benchmarks, one of them twice.** The convergence pattern holds on all of them, and "the convergence point is a property of the corpus" is an interpretation of five numbers, not a law.
4. **`tiebreak` is untested where ties are common.** A retriever returning quantised or bucketed scores would give it something to do; this one does not.
5. **Latency is 2 to 4 ms a query on top of retrieval** and was never the binding constraint, so nothing here tests whether the cost would matter at scale.
