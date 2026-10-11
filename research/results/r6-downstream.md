# R6 — does better retrieval change what a model answers?

**Verdict: INCONCLUSIVE, as registered.** `store_all` beats the best simple arm
by 20% of the measured headroom; the pre-registered bar was 40%. It is not
killed either — it is above the baseline, just not far enough.

And the most useful thing here is that **my first prediction was wrong in the
direction that matters**: giving the model the whole corpus did *not* beat
retrieval. Retrieval won, at **a third of the prompt tokens**.

- **Registration:** [r6-downstream-retrieval.md](../prereg/r6-downstream-retrieval.md), with one dated amendment (3 seeds not 5) made before any number was seen
- **Model:** `qwen2.5:7b` via Ollama, temperature 0, running on CPU
- **Run:** 2026-10-11, dev split, 3 seeds, k=3, 30 cases of which **22 graded on correctness**
- **Raw:** [r6-dev-raw.json](r6-dev-raw.json)
- Test split: running; this document will be amended with it rather than quietly completed.

---

## 1. The numbers

| arm | correctness | 95% CI | critical present | gate violations | abstain precision | prompt tokens |
|---|---|---|---|---|---|---|
| `no_memory` | 0.182 | [0.182, 0.182] | 0.000 | **0** | 1.000 | 66 |
| `all_memory` | 0.758 | [0.727, 0.773] | 0.857 | **0** | 0.333 | 294 |
| `store_plain` | 0.712 | [0.682, 0.727] | 0.643 | **0** | 0.667 | 103 |
| **`store_all`** | **0.788** | [0.773, 0.818] | 0.714 | **0** | 0.667 | 103 |
| `oracle_memory` | 0.909 | [0.909, 0.909] | 0.857 | **0** | 1.000 | 85 |

## 2. The verdict, applied exactly as registered

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

## 3. Prediction 1 was wrong, and that is the result worth having

The registration predicted:

> `all_memory` beats `store_plain`. The corpora are 18–20 memories and a modern
> model reads all of them; if so, **retrieval quality matters less than the
> ranking numbers suggest**, and that is the finding.

It does beat `store_plain` (0.758 against 0.712). It **loses to `store_all`**
(0.758 against 0.788) — and does it with **294 prompt tokens against 103**.

So on this benchmark, with this model: **retrieval beats stuffing the context,
at a third of the tokens.** That is the first downstream evidence in this
project that selection is worth anything at all, and it was predicted not to
happen.

The restraint it needs: 294 tokens is a small context by any modern standard.
A model with a large window and a corpus this size has no reason to struggle,
and it still did worse than selection. What that cannot tell us is what happens
at a corpus size where stuffing is not an option, which is where retrieval
obviously matters and where this benchmark has nothing to say.

## 4. The mechanisms earn their first downstream number

`store_all` − `store_plain` = **+0.076 correctness** (0.788 against 0.712), the
same configuration difference that was worth +0.042 nDCG on this split. Source
roots, premise promotion and temporal filtering together move answers, not just
rankings.

Also +0.071 on critical-fact presence (0.714 against 0.643), which is the
channel the effect should travel through if the story is right.

Set against it: the mechanisms were measured as **marginal-to-negative** on the
expanded test split under lexical retrieval
([scifact-external.md](scifact-external.md) §4), so this is dev-only evidence
for them and the test split is the number that matters.

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

That is a safety argument for retrieval that has nothing to do with
correctness: **a smaller, better context does not just cost fewer tokens, it
makes the model more willing to admit it does not know.** Two unanswerable
cases on this split, so it is a direction rather than an estimate.

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

> Pre-registered threshold not met: `store_all` closes 20% of the measured
> headroom against a registered bar of 40%. **Inconclusive**, not supported.
>
> But the prediction that retrieval would prove unnecessary — that a model
> handed 18–20 memories would do as well as one handed the right 3 — was
> **wrong**. Retrieval won by 3 points at a third of the tokens, and the
> mechanisms added 7.6 points of correctness on top. This is the first
> downstream evidence in the project that selection changes answers.
>
> The conversion factor is now measured rather than assumed: the model recovers
> about 40% of what nDCG penalises. That makes retrieval work worth less
> downstream than the ranking numbers imply — and it is the number every
> earlier milestone was missing.
>
> And one finding nobody asked for: **stuffing the context halved the model's
> willingness to say it could not tell.** A selected context is not only
> cheaper, it is more honest.
