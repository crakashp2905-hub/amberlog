# Abstention: four signal families measured, and why pooling kills the only one that works

**The retrieval stage carries an abstention signal that is real within a
question type and destroyed by pooling across types.** Four families measured
on LongMemEval's 500 instances, 30 of them deliberately unanswerable:

| signal family | result |
|---|---|
| an absent query term (4 variants) | **nothing** — precision 0.067, which is the 30/500 base rate |
| chain coverage share | **nothing** — d = 0.00, it is 1.000 on every instance |
| absolute match quality | **real but confounded** — right direction in 4 of 4 question types, pooled AUC **0.319** |
| rarity-weighted coverage (3 variants) | **worse than the raw score** — d 0.45 against 0.56 |

Best achievable with a global threshold: **F1 0.206** — abstain on 23% of
answerable questions to catch 53% of unanswerable ones. Not shippable.

- **Benchmark:** [LongMemEval](longmemeval.md) oracle split, 470 answerable / 30 unanswerable
- **Run:** 2026-10-12. Deterministic; no model calls
- **Context:** abstention is this project's most-replicated failure — 0.000 on `relevance_v2`'s nine designed cases, 1/9 for the chain arm in [P1](p1-evidence-chain-reconstruction.md), 0–7% externally on LongMemEval

---

## 1. Why term absence cannot work

The obvious signal, and the one [P2](p2-context-sufficiency.md) §5 pointed at:
the information needed for abstention is in the query terms that P2's
`reachable_terms` filter *discarded*, because that filter kept only terms the
corpus contains and so could never notice an absence.

Four variants, each asking "would this say insufficient?":

| signal | fires on 30 unanswerable | fires on 470 answerable | precision |
|---|---|---|---|
| any absent content term | 26 (0.87) | 360 (0.77) | 0.067 |
| absent with no prefix-5 relative | 22 (0.73) | 301 (0.64) | 0.068 |
| unseen capitalised name | 29 (0.97) | 410 (0.87) | 0.066 |
| unseen name or identifier | 29 (0.97) | 412 (0.88) | 0.066 |

**Every variant fires on 77–88% of answerable questions**, and precision sits
at the base rate to three decimals. The recall looks excellent and means
nothing: a signal that fires on nearly everything has no information.

The reason is simple once measured. LongMemEval's questions are
*paraphrases* — "What was the first issue I had with my new car after its
first service?" against a corpus that says it differently — so a query term the
corpus lacks is the normal case, not the exceptional one. P2's filter was not
throwing away the signal; there was no signal to throw away.

**Chain coverage is the same story with a cleaner number.** `EvidenceChain`
reports what it could not cover, and that share is **1.000 on every instance,
answerable or not** (d = 0.00). Exactly what P2 §5 diagnosed: token coverage
completes from memories that are not about the question.

## 2. The signal that exists, and the sample that nearly fooled me

A matched sample of 30 unanswerable against 32 answerable showed the mean of
the top 10 retrieval scores separating at **d = 0.68** — unanswerable 0.310,
answerable 0.456. Medium-to-large, and the most promising thing measured.

On the full population, **AUC = 0.319**: *below* chance, with the effect
reversed. Something was wrong with the sample, and it was mine — a stride over
a file sorted by question type, so the comparison was partly between question
kinds rather than between answerable and unanswerable.

Broken out, the mean of the top 10 scores:

| question type | answerable | unanswerable |
|---|---|---|
| knowledge-update | 0.494 (72) | **0.468** (6) |
| multi-session | 0.409 (121) | **0.309** (12) |
| single-session-user | 0.257 (64) | **0.173** (6) |
| temporal-reasoning | 0.446 (127) | **0.290** (6) |
| single-session-assistant | 0.556 (56) | — |
| single-session-preference | 0.291 (30) | — |

**The effect is real and in the right direction in all four types that have
unanswerable instances.** It is destroyed by pooling because the between-type
spread (0.257 to 0.556) is **2 to 10 times** the within-type gap (0.026 to
0.156), and the unanswerable instances sit entirely in the middle-and-lower
types — none in the highest-scoring `single-session-assistant`.

So the honest statement is not "there is no signal". It is: **the signal needs
a per-query reference point, and an absolute score is not one.**

## 3. The three calibrations tried, all of which failed

If the problem is a missing reference point, the fix is a normaliser. Three,
and none of them helped:

| normalisation | separation |
|---|---|
| raw `mean of top 10` | d = 0.68 (matched sample) |
| within-result: `top / mean of top 10` | **d = 0.17** |
| by query IDF mass: `top / sum of query term IDF` | d = 0.48 |
| matched share of query IDF mass | d = 0.45 |

**Within-result normalisation destroys the signal entirely** (0.17), which says
the information is in absolute magnitude rather than in the shape of the result
list. And normalising by the query's own informational weight — the principled
version, and my own hypothesis — made it **worse than the raw score**. The
unanswerable questions here tend to be compound ("which did I do first, X or
Y?"), so dividing by query weight removes exactly the thing that distinguishes
them.

## 4. What a global threshold would buy

Chosen on this data, so an upper bound rather than a forecast:

```
best achievable F1 = 0.206 at a threshold of 0.2656
  precision 0.128   recall 0.533
  abstains on 109 of 470 answerable questions (23.2%)
  to catch 16 of 30 unanswerable ones
```

A memory system that refuses to answer **a quarter of the questions it could
answer**, and still misses half the ones it should refuse, is worse than one
that always answers. This is the quantitative reason the item does not ship.

## 5. What this settles, and what it moves

**Settles:** abstention is not a retrieval-stage problem, and the four cheapest
hypotheses are eliminated with numbers rather than with an argument. P2's
diagnosis — "token presence is not evidence about a conjunction" — is confirmed
and extended: neither is token *absence*, nor chain coverage, nor absolute
score, nor three ways of calibrating it.

**Moves:** the open problem is now specific. A retrieval-stage abstention
signal needs a per-query reference for *how well this query should be expected
to match*, and the obvious references fail. The candidates left are not
retrieval-side:

- **The reading stage.** A model given the context deciding it does not answer the question. [R6](r6-downstream.md) measured the related effect from the other side — stuffing a context makes a model *less* willing to abstain, and it is the one R6 finding that survived its frozen split. That makes the reading stage the most likely place and R6 the warning about measuring it.
- **Entailment.** The same conclusion `implied_by_default` reached from another direction: "did any memory *assert* something about the asked subject" is not a question similarity can answer. Typed edges and assertion structure are the shared prerequisite.

**Also recorded:** I nearly published d = 0.68 from a confounded sample. The
full-population AUC is what caught it, and the lesson is specific — on a
benchmark whose file is sorted by question type, any sample that is not
stratified is a comparison between types. `experiments/longmemeval_bench.py`
samples stratified for exactly this reason, and the probe that produced 0.68
did not.

## 6. What this does not establish

1. **One benchmark, 30 unanswerable instances.** Thirty is few, and they are unevenly spread across four of six question types. The within-type direction being right 4 times out of 4 is the strongest claim available and it rests on 6, 12, 6 and 6 instances.
2. **Lexical retrieval only.** A trained embedder's score distribution might calibrate differently; untested, and the type-confound would still have to be dealt with.
3. **The oracle split.** Median 23 turns. The `s` split's 491-turn haystacks would change every absolute score, though the confound is a property of the question types rather than of the haystack.
4. **"Reports insufficiency" is my metric on their data.** LongMemEval's own retrieval evaluation skips these instances.
5. **No per-type threshold was tried.** It would work on this data by construction — the within-type effect is real — and would be fitted to it. A real version needs the type, or a proxy for it, available at query time, which a deployment does not have.
