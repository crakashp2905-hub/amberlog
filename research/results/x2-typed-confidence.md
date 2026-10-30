# X2 — a typed decision model for abstention: NOT SUPPORTED, and it is calibration

**Kev-0.8B scores F1 0.1739 against a registered bar of 0.5514 — and it loses
to a one-line lexical score.** AUC 0.6286 against the best baseline's 0.7113.
The share of claimed headroom is **negative**: −0.105.

**The failure is calibration rather than ignorance, and that distinction is
the finding.** The model's entire output range sits below indifference. It
calls **470 of 500** instances unanswerable; the highest P(answerable) it ever
produced, over 500 calls, was **0.786**; and the median gap between the two
classes is **0.03** (0.261 answerable against 0.231 unanswerable). The signal
points the right way and is far too compressed to threshold.

- **Registration:** [x2-typed-confidence.md](../prereg/x2-typed-confidence.md), written before the model finished installing and before any call
- **Mechanism:** `memory-fabric/adapters/systemone.py`, one `noul` question per instance
- **Harness:** `experiments/x2_typed_abstention.py`
- **Run:** 2026-10-14, LongMemEval `s` split, 500 instances (30 unanswerable), k=10, `jaredpalmer/kev-0.8b` on CPU via its own server, **500 calls, 803,738 input tokens, 14,931 s (4.15 h)**
- **Raw:** [x2-run.json](x2-run.json) · pilot: [x2-pilot-run.json](x2-pilot-run.json)

---

## 1. The table

| arm | AUC | best F1 | precision | TPR | FPR |
|---|---|---|---|---|---|
| `mean_top10` retrieval score | **0.7113** | 0.2321 | 0.159 | 0.433 | 0.147 |
| `top1` retrieval score | 0.7107 | 0.2095 | 0.122 | 0.733 | 0.336 |
| content-term `coverage` | 0.6813 | **0.2524** | 0.178 | 0.433 | 0.128 |
| **`typed` (Kev-0.8B)** | **0.6286** | **0.1739** | 0.100 | 0.667 | 0.383 |
| `always_abstain` (degenerate) | 0.5 | 0.1132 | 0.060 | 1.0 | 1.0 |
| `oracle` | 1.0 | 1.0 | 1.0 | 1.0 | 0.0 |

```
B = 0.2524   C = 1.0000   bar = B + 0.40 * (C - B) = 0.5514
typed = 0.1739      share of headroom = -0.105
```

**NOT SUPPORTED.** And the comparison that matters is not against the bar but
against the row below it: the typed model's F1 of 0.1739 is nearer the
**degenerate always-abstain arm** (0.1132) than any real baseline. No arm beat
the oracle.

The three baselines were **re-measured in this run** rather than quoted, which
is the one thing X1's registration got wrong and the reason principle 8d
exists. They reproduce their published values exactly.

## 2. Calibration — the thing this class of model was chosen for

| | measured | reference |
|---|---|---|
| ECE | **0.6622** | — |
| Brier | **0.5037** | Kev-0.8B's card: **0.481** on new sources |
| accuracy at p=0.5 | **0.116** | base rate 0.94 answerable |
| mean confidence, all | 0.4634 | — |
| mean confidence, **on errors** | **0.4776** | — |
| mean P(answerable) when answerable | 0.2805 | — |
| mean P(answerable) when **un**answerable | 0.2352 | — |

**Accuracy at the natural threshold is 0.116.** Ninety-four per cent of these
instances are answerable and the model says they are not, so thresholding at
0.5 is wrong about seven questions in eight. A detector that always answered
"answerable" would score 0.94.

This is **not** a model that cannot tell the two apart — AUC 0.6286 is above
chance, and the class medians differ in the right direction. It is a model
whose probabilities are on the wrong scale for this task, which is exactly
what a **temperature fitted on someone else's distribution** looks like. Kev
ships a per-checkpoint temperature of 2.351 and its own documentation
recommends refitting on held-out data from your own domain before setting any
act-or-escalate threshold; the vendor-reported effect of doing so on its
sibling Laya is an ECE of 0.466 falling to 0.081.

So the registered zero-shot measurement is done, and it is the baseline a
refit now has to beat. §4 of the registration said the zero-shot case was
measured first for precisely that reason.

> **Corrected 2026-10-14 by [X2b](x2b-recalibration.md).** The refit was run
> and the diagnosis above is half right. The probabilities *were* badly
> scaled, and refitting takes ECE from 0.6631 to **0.0083**. But the implied
> conclusion -- that the scale was the problem -- is wrong twice over.
>
> **It cannot help, provably:** AUC and best-F1 are invariant under any
> strictly monotone transform, and a temperature or Platt rescaling is one, so
> **no refit can move this result's primary metric.** Both are identical to
> four decimals across every arm.
>
> **And it achieves its calibration by discarding the signal:** the fitted
> rescaling outputs a mean probability of 0.94 on a population that is 94%
> answerable, which is a constant predictor at the base rate. Perfectly
> calibrated, perfectly uninformative.
>
> So the heading of this section should be read narrowly. The *numbers* were
> bad for calibration reasons; the *mechanism* fails because its
> discrimination is weaker than a lexical score's, and that is untouched by
> scale. Get the discrimination first.

## 3. The predictions, scored

1. **"It will not reach 0.5514, and the premise measurement is why."** **Confirmed.** 0.1739. The premise finding stands: an unanswerable question's retrieved context already contains 79% of its distinctive content terms, so the turns are about the subject and what is missing is one specific fact.
2. **"Brier will be worse than the published 0.481."** **Confirmed**, 0.5037. A macro average over fourteen datasets does not transfer to a single adversarial task built to be partially answerable.
3. **"Confidence will be higher on errors than the overall mean."** **Confirmed**, 0.4776 against 0.4634 — the prediction I said I would most like to be wrong about, because it is the one that decides whether the probability is usable as a logged propensity. It is not, at this checkpoint.
4. **"The 0.8B checkpoint is the wrong size and I am running it anyway."** Stands. 4B needs ~8 GB resident against 3.1 GB free, and its published Brier is 0.269 against 0.481. **This result does not transfer to 4B**, which was written down before the run rather than offered afterwards.

**The pilot disagreed with the run on prediction 3, and that is worth keeping.**
Twenty instances said confidence on errors was *lower* (0.433 against 0.467);
five hundred reversed it. The pilot was a harness check and was labelled one,
and its base rate was 50% against the population's 6%. A 20-instance
stratified subset is not a small version of this measurement.

## 4. What it cost, and what that implies

500 calls, 803,738 input tokens, **4.15 hours** on 8 CPU cores with no
discrete GPU. About 30 s a call.

The same hardware ceiling as [X1 §8](x1-extraction.md): the question is not
whether a typed model is affordable in principle — it is 0.8B — but that
nothing here can run the checkpoint whose calibration is worth having. A GPU
would not change a number in §1, since those are properties of this
checkpoint's answers, but it would make 4B and 9B measurable, which is where
the published Brier halves.

## 5. What this does not establish

- **One checkpoint, zero-shot, at its shipped temperature.** Nothing about 4B, 9B or 27B, and nothing about a refit, which §2 argues is the single most likely repair and which the registration already frames as a secondary.
- **Nothing about the `choice` form**, which is where the measurement actually pointed. Asked *"which of these three axle rules applies to a vehicle with the standard axle set?"* the same checkpoint picked the right one unprompted. A closed three-option question is a much easier one than "is this context sufficient", and [X3](x3-scoped-adjustments.md) has since closed the dev half of that family without a model at all.
- **Nothing about acting on the signal.** §1 of the registration gives five results on why reporting and acting are different claims, and this measured a report.
- **The `checks` block is absent from this run's JSON**, because the run was launched before `experiments/checks.py` was wired into this harness. The ceiling check was computed inline and reported (`any_arm_beat_the_oracle: []`); the direction check was not, and it is the one that would matter here, since this experiment's own baseline is the signal `abstention-signals.md` reported as its own complement. Future runs carry it.
- **The run was lost twice before it completed**: once to a formatting error after all 500 instances, once to the server going away at 175. The answer cache that makes it resumable was added after the second, and this run used it.
