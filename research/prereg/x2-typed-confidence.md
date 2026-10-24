# Pre-registration — X2: a typed decision model for abstention

**Registered 2026-10-14, before Kev has finished installing and before any
model call.** The order is deliberate and is the whole lesson of X1: its
registration quoted a baseline from another document's table and the primary
was invalid before any arm ran ([principle 8d](../../AGENTS.md)). Here the
baselines are re-measured in the same run, on the same metric, at the same
budget, and the numbers below were produced by `x1_abstention_premise.py`
yesterday rather than copied from prose.

## 1. Why this, and why abstention rather than the other two candidates

A **System One** model answers *typed* questions about a text and returns a
probability distribution over a closed option set, rather than generating
prose. [Kev](https://github.com/jaredpalmer/kev) serves TypeSafe's System One
API locally under Apache-2.0, in four sizes from 0.8B to 27B.

Three measured gaps in this project are closed option sets:

| gap | the typed question | why not first |
|---|---|---|
| **abstention** | *"Can this question be answered from this context?"* — `noul` | — **this is the one** |
| sibling-rule choice | *"Which of these three axle rules applies to a vehicle with the standard axle set?"* — `choice` | needs the quantity-match prefilter built first; no baseline measured yet |
| exposure propensity | a distribution to log per decision (principles 4 and 5) | no baseline, and no decision rule to compare against |

**Abstention is first because it is the only one where a registration can be
honest today.** The baseline is measured on the exact metric, the population is
third-party (LongMemEval), the harness exists, and the output is a **report**
rather than an action.

That last point is a product argument, not a convenience.
[PA′](../results/phase-a-prime-attribution.md) measured genuine leave-one-out
attribution — good inference — and it still lost to withdrawing nothing
(`fabric_loo` 0.483 against `shared_memory` 0.608). Five results now say that
*acting* on an inferred signal loses even when the inference is sound. A
calibrated probability does not change that economics. So the first use of one
must be a place where the system **says** it cannot answer, not a place where
it withholds a memory.

## 2. Primary metric and threshold

**Population:** LongMemEval `s` split, all 500 instances — 30 `_abs`
(unanswerable) against 470 answerable. Third-party data and third-party labels.

**Mechanism:** retrieve the top 10 turns with the product's `LexicalIndex`,
exactly as the baseline does, and ask Kev **one `noul` question** about that
context. The retrieval is identical across arms; the only difference is what
reads the result.

**Primary: best achievable F1 at a single global threshold**, chosen on this
data and therefore an upper bound for every arm equally.

F1 and not AUC, because the family was rejected on its **operating point**, not
its discrimination: `research/results/abstention-signals.md` §4 records
AUC 0.682 alongside an unshippable F1 0.206, and §7 explains that the
discrimination was never the problem.

```
B = max(best_f1) over the registered baselines, re-measured in this run = 0.2524
C = oracle (a detector that knows the label)                            = 1.0000
support iff best_f1 >= B + 0.40 * (C - B) = 0.5514
```

**The three registered baselines**, all measured 2026-10-13 on this exact
population and metric by `experiments/x1_abstention_premise.py`:

| baseline signal | AUC | best F1 |
|---|---|---|
| `mean_top10` retrieval score | 0.7113 | 0.2321 |
| `top1` retrieval score | 0.7107 | 0.2095 |
| **content-term `coverage`** | 0.6813 | **0.2524** |

**8d check — is each baseline measured on the primary metric, at the primary
budget, on the primary split?** Yes: F1, k=10, `s`. This is the check X1
failed, and the trap here is specific and worth naming — **AUC 0.682 is
already achieved by a one-line lexical score**, so a bar written against 0.5
would be passed by the baseline itself.

**8c check — is the primary trivially maximised by a baseline?** No. The
best registered baseline reaches 0.2524. A degenerate "always abstain" detector
reaches F1 0.113 (recall 1.0, precision 30/500), and it is reported every run.

**8b check — can any arm beat the oracle?** The oracle knows the label, so
F1 1.0 bounds everything, and "did any arm exceed it" is checked on every run.

**Abandonment clause.** If `C − B <= 0.05`, abandoned rather than
reinterpreted. It is 0.748, so the clause is not close.

**Seeds.** The model is run at its shipped temperature with a fixed question
and fixed retrieval, so the arm is deterministic; `--seeds` varies the
retrieval tie-breaking only. The threshold sweep is exhaustive rather than
sampled.

## 3. Secondary metrics, reported always, decisive for none

- **ECE and Brier.** The reason to want this class of model is calibration, so these are the figures that say whether it delivered the thing it was chosen for. Kev's own cards report Brier on sources it never trained on: **0.481 for Kev-0.8B, 0.269 for Kev-4B**. This project is a new source, so those are the numbers to beat and the comparison is direct.
- **Cost.** Calls, tokens, wall time, through a client that logs all three. CPU only: there is no discrete GPU on this machine, which is what made `gemma2` a batch job in X1 at 47–77 s a statement.
- **The full ROC**, not one threshold, because a single operating point chosen on the data is the thing §4 of the abstention result warns is an upper bound.
- **Confidence on the wrong answers specifically.** The failure mode to detect is *confident and wrong*: Kev's sibling Laya is reported at **0 accuracy with 0.952 confidence** on Khmer. Mean confidence on errors is reported separately from mean confidence overall, because the average hides exactly that.

## 4. Predictions

1. **It will not reach 0.5514, and the premise measurement is why.** An unanswerable question's retrieved context already contains **79% of its distinctive content terms** (`x1-extraction.md` §5). The turns are *about* the subject; what is missing is a specific fact. Deciding that requires knowing what the question needs, which is most of answering it — and this model is 0.8B.
2. **Brier will be worse than Kev's published 0.481 for this checkpoint**, because that figure is a macro average over fourteen datasets in five areas and this is a single adversarial task built to be partially answerable.
3. **Confidence will be higher on errors than the overall mean.** This is the prediction I would most like to be wrong about, because it is the one that decides whether the probability is usable for anything at all, including as a logged propensity.
4. **The 0.8B checkpoint is the wrong size and I am running it anyway**, because 4B needs ~8 GB resident and this machine has 15.7 GB total with the X1 primary still holding memory. If the 0.8B arm fails, that result does **not** transfer to 4B, and saying so now prevents a convenient reading later.

## 5. What a pass would not establish

Nothing about acting on the signal — §1 gives five results on why reporting and
acting are different claims. Nothing about the other two candidate gaps, each
of which needs its own baseline. Nothing about Jev, which is hosted and not
measured here. And nothing about a fine-tune: Kev's documentation recommends
training on a few hundred labelled examples from your own domain rather than
treating any checkpoint as a zero-shot drop-in, and this registration
deliberately measures the zero-shot case first so that a fine-tune has
something to be compared against.
