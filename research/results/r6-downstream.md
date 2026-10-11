# R6 — does better retrieval change what a model answers?

**dev: INCONCLUSIVE. test: ABANDONED — there was no headroom to divide.**

On the frozen split, handing the model the entire corpus scored **exactly what
handing it the oracle's memories scored** (0.792 against 0.792). The
registration's section 4 clause fired on its own: *if `C` − `B` ≤ 0.05 the
comparison is abandoned, not reinterpreted.* The harness printed it without
being asked.

**And the dev result did not replicate.** On dev, retrieval beat stuffing the
context (0.788 against 0.758) and I wrote that up as the finding worth having.
On test it goes the other way (0.750 against 0.792). Two splits disagreeing
means **I do not know**, and the dev sections below are left standing so the
overclaim is visible rather than edited away.

- **Registration:** [r6-downstream-retrieval.md](../prereg/r6-downstream-retrieval.md), with one dated amendment (3 seeds not 5) made before any number was seen
- **Model:** `qwen2.5:7b` via Ollama, temperature 0, running on CPU
- **Runs:** 2026-10-11. dev (30 cases, 22 graded) and the frozen test split (20 cases, 16 graded); 3 seeds each, k=3
- **Raw:** [r6-dev-raw.json](r6-dev-raw.json) and [r6-test-raw.json](r6-test-raw.json)

---

## 1. The numbers

| arm | correctness | 95% CI | critical present | gate violations | abstain precision | prompt tokens |
|---|---|---|---|---|---|---|
| `no_memory` | 0.182 | [0.182, 0.182] | 0.000 | **0** | 1.000 | 66 |
| `all_memory` | 0.758 | [0.727, 0.773] | 0.857 | **0** | 0.333 | 294 |
| `store_plain` | 0.712 | [0.682, 0.727] | 0.643 | **0** | 0.667 | 103 |
| **`store_all`** | **0.788** | [0.773, 0.818] | 0.714 | **0** | 0.667 | 103 |
| `oracle_memory` | 0.909 | [0.909, 0.909] | 0.857 | **0** | 1.000 | 85 |

## 1a. The frozen test split

| arm | correctness | 95% CI | critical present | gate violations | abstain precision | prompt tokens |
|---|---|---|---|---|---|---|
| `no_memory` | 0.250 | [0.250, 0.250] | 0.000 | **0** | 1.000 | 67 |
| `all_memory` | **0.792** | [0.688, 0.875] | 0.895 | **0** | **0.000** | 299 |
| `store_plain` | 0.750 | [0.688, 0.812] | 0.737 | **0** | 1.000 | 105 |
| `store_all` | 0.750 | [0.688, 0.812] | 0.684 | **0** | 1.000 | 105 |
| `oracle_memory` | **0.792** | [0.750, 0.812] | 0.895 | **0** | 1.000 | 86 |

```
best simple arm  B = 0.792   (all_memory)
ceiling          C = 0.792   (oracle_memory)
headroom             +0.000  <= 0.05  ->  ABANDONED
```

**Perfect selection is worth nothing here.** Not a little; nothing. On these 16
graded cases a model given 19 memories answers as well as one given the 3
correct ones, so there is no quantity for retrieval to capture, and a threshold
on it would be the H3 mistake: registering a margin larger than the ceiling.

That is a verdict on **my benchmark**, not on retrieval. The reason is the one
SciFact already identified: my distractors are *clearly* wrong rather than
near-misses in the same technical register, so a competent model ignores them.
19 short facts with 16 obvious non-answers is not a retrieval problem for
`qwen2.5:7b`.

What would make it one: corpora a model cannot read in full, and distractors
plausible at the sentence level. Both now sit above any ranker in the backlog.

## 2. The dev verdict, applied exactly as registered

```
best simple arm  B = 0.758   (all_memory)
ceiling          C = 0.909   (oracle_memory)
headroom             +0.151  (> 0.05, so the comparison stands)
threshold        B + 0.40 × headroom = 0.8184
store_all            0.788
```

`0.788 < 0.8184`, so **not supported**. `0.788 > 0.758`, so **not killed**.
**Inconclusive**, and reported as inconclusive rather than argued either way.

`store_all` closes **20% of the headroom** where 40% was required. I am
recording the shortfall rather than observing that it is "most of the way
there", because the threshold was registered precisely so that this moment
could not be renegotiated.

## 3. Prediction 1 on dev, and the reversal on test

The registration predicted:

> `all_memory` beats `store_plain`. The corpora are 18–20 memories and a modern
> model reads all of them; if so, **retrieval quality matters less than the
> ranking numbers suggest**, and that is the finding.

It does beat `store_plain` (0.758 against 0.712). It **loses to `store_all`**
(0.758 against 0.788) — and does it with **294 prompt tokens against 103**.

So on **dev**: retrieval beats stuffing the context, at a third of the tokens.

**On test it reverses.** `all_memory` 0.792 against `store_all` 0.750 — the
prediction the dev split refuted is the one the frozen split supports.

Together the two splits say the honest thing: **on a benchmark whose corpora a
model can simply read, selecting or not does not reliably matter.** The dev
direction was the more interesting result and it is the one that failed to
replicate, which is the ordinary way an interesting result behaves.

The token difference survives both splits and is not in dispute: 103 against
294–299, a roughly 3x saving for no measured loss on test and a gain on dev.
That is a cost argument for retrieval rather than a quality one, and worth
keeping separate from the quality question.

## 4. The mechanisms earn their first downstream number

`store_all` − `store_plain` = **+0.076 correctness** (0.788 against 0.712), the
same configuration difference that was worth +0.042 nDCG on this split. Source
roots, premise promotion and temporal filtering together move answers, not just
rankings.

Also +0.071 on critical-fact presence (0.714 against 0.643), which is the
channel the effect should travel through if the story is right.

Set against it, decisively: on the frozen test split `store_all` and
`store_plain` are **identical at 0.750**, and `store_all` is *worse* on
critical-fact presence (0.684 against 0.737). The +0.076 is dev-only, dev is
where these mechanisms were tuned, and the split that matters shows nothing.
With their −0.013 nDCG on the same split
([scifact-external.md](scifact-external.md) section 4), the honest position is
that **the mechanisms have no demonstrated downstream benefit.**

They stay enabled because they address indirect evidence and copied sources
that neither benchmark can currently test — an argument from design rather than
from evidence, and it should be labelled as one.

## 5. Stuffing the context makes a model worse at abstaining

The finding I did not predict at all.

| arm | abstention precision on `unanswerable` cases |
|---|---|
| `no_memory` | 1.000 |
| `all_memory` | **0.333** |
| `store_plain` / `store_all` | 0.667 |
| `oracle_memory` | 1.000 |

Given the whole corpus, the model finds *something* to say two times out of
three on a question the corpus cannot answer. Given a selected context it
abstains twice as often, and given exactly the right memories — none, for an
unanswerable case — it abstains every time.

The frozen split points the same way and harder: `all_memory` abstains on
**0 of 1** unanswerable cases, where every selected arm abstains on 1 of 1.

So this is the one effect that **replicates across both splits**: a smaller,
better context does not merely cost fewer tokens, it makes the model more
willing to admit it does not know. Three unanswerable cases in total, so a
direction rather than an estimate — and the only direction here that survived
the frozen split.

## 6. Prediction 2 was right

> The gap between `store_all` and `oracle_memory` is smaller than the nDCG gap,
> because a model recovers from a mediocre context more often than a metric
> rewards.

Correctness gap: 0.909 − 0.788 = **0.121**. nDCG gap on the same split:
1.000 − 0.799 = **0.201**. The model recovers about 40% of what the retrieval
metric penalises.

This is the conversion factor R1–R5 assumed and never measured, and it cuts
both ways: it means retrieval improvements are worth **less** downstream than
nDCG suggests, and it means a ranker chasing the last few nDCG points is
chasing something the model partly fixes for free.

## 7. Prediction 3 was right and worth little

`no_memory` at 0.182 against everything else above 0.71. The corpus is
load-bearing, which establishes that the benchmark is not answerable from the
model's own knowledge — necessary, and no evidence for anything this project
builds.

## 8. Zero gate violations, across every arm and seed

Including `all_memory`, which asks for the entire corpus. The `must_not_expose`
memories — relevant, and refused by authorisation or retraction — never reached
a prompt. That is the enforcement layer doing its job in the one place it most
matters, and it is reported as zero rather than as a pass because a non-zero
value would have failed the run whatever the correctness column said.

## 9. What this does not establish

1. **Inconclusive is not "nearly supported".** The bar was 40% of headroom and this is 20%.
2. **One model, on CPU, 3 seeds.** `qwen2.5:7b` at temperature 0; a different model could order the arms differently, and the amendment to 3 seeds widened every interval.
3. **22 graded cases.** The intervals are over 3 seeds of the same 22 cases, so they capture prompt-order variance and nothing about case sampling.
4. **Substring grading.** Crude by design — a rule a reader can check beats a judge whose agreement with the labels is unmeasured — but it will mark a correct answer wrong if the model paraphrases past the key, which inflates nothing and deflates everything equally.
5. **Dev only so far.** The test split is running. Dev is where the mechanisms were tuned, so its +0.076 is the optimistic reading by construction.
6. **My benchmark.** One author's cases and labels; [SciFact](scifact-external.md) is the external check on retrieval, and there is no external check on this downstream question.

## 10. The honest summary

> **Dev: inconclusive** — `store_all` closes 20% of the measured headroom
> against a registered bar of 40%. **Test: abandoned** — perfect selection is
> worth **+0.000** there, so the question cannot be asked at all.
>
> The dev finding I was most pleased with, retrieval beating a stuffed context
> at a third of the tokens, **did not replicate**. The frozen split reverses
> it. Two splits disagreeing means I do not know, and the dev sections above
> are left standing so the overclaim stays visible.
>
> The mechanisms' +0.076 downstream gain is dev-only, dev is where they were
> tuned, and on the frozen split they are identical to plain retrieval and
> slightly worse on critical-fact presence. **They have no demonstrated
> downstream benefit.**
>
> Two things survive. The **~3x token saving** holds on both splits for no
> measured quality loss, which is a cost argument rather than a quality one.
> And **stuffing the context makes a model less willing to abstain**, on both
> splits, which is a safety argument with nothing to do with correctness.
>
> The strongest conclusion is about the benchmark rather than the retriever:
> **a corpus a model can simply read does not pose a retrieval problem.** My
> distractors are too obviously wrong — exactly what SciFact showed. Harder
> corpora come before any ranker.
