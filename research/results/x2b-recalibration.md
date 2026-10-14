# X2b — the calibration is fixable, and fixing it proves the signal is the problem

**Refitting Kev-0.8B's temperature on our own data takes ECE from 0.6631 to
0.0083 — better than the vendor's own reported figure for a refit — and
changes the registered primary by exactly nothing.** AUC and best-F1 are
identical to four decimals across every arm, which is not a surprise but a
theorem: a strictly monotone rescaling permutes no scores.

**And the way it achieves that calibration is the finding.** The fitted
rescaling outputs a mean probability of **0.94** on a population that is 94%
answerable. It learned the prior and discarded the signal. A detector that
always says "answerable" is perfectly calibrated and perfectly useless, and
ECE and Brier cannot tell the difference.

So this **corrects [X2's own diagnosis](x2-typed-confidence.md)**. That result
called the failure "calibration rather than ignorance". The first half is
right — the probabilities were badly scaled. The implication was wrong:
rescaling them does not help, because the discrimination underneath is what
binds.

- **Source:** [x2-run.json](x2-run.json) — X2's 500 saved answers. **No model calls.**
- **Harness:** `experiments/x2_recalibrate.py`
- **Run:** 2026-10-14, 5 seeds, fitted on half and reported on the held-out half, stratified by class so each half holds 15 of the 30 unanswerable instances
- **Raw:** [x2b-run.json](x2b-run.json)

---

## 1. The table

Held-out halves, averaged over 5 seeds.

| arm | ECE | Brier | accuracy @ p=0.5 | mean p | AUC | best F1 |
|---|---|---|---|---|---|---|
| as shipped (T = 2.351) | 0.6631 | 0.5037 | 0.116 | 0.277 | **0.6488** | **0.1986** |
| temperature refitted | 0.4426 | 0.2522 | 0.116 | 0.497 | **0.6488** | **0.1986** |
| **Platt refitted** (scale + bias) | **0.0083** | **0.0563** | 0.940 | 0.940 | **0.6488** | **0.1986** |

Base rate: 0.94 answerable. (AUC here is 0.6488 rather than X2's 0.6286
because these are held-out halves averaged over five seeds rather than the
single full population.)

## 2. What is provable, and was stated before the run

> **AUC and best-achievable-F1 are invariant under any strictly monotone
> transform of the score.** Best F1 is already a sweep over *every* threshold,
> so rescaling moves the optimal threshold with the scores and changes
> nothing. A temperature and a Platt rescaling are both strictly monotone.

The module docstring says this before the experiment runs, and the harness
**checks it on every run** rather than trusting it: a difference across arms
would mean the transform is not monotone or the metric is not threshold-free,
and either is worth knowing. Measured: identical.

**X2's NOT SUPPORTED is therefore robust to recalibration.** No refit of any
kind can rescue it, and no further refit needs running to establish that.

## 3. A temperature cannot shift a distribution, measured

Temperature scaling sharpens or flattens **around 0.5**. X2's problem is a
*shift* — both classes sat near 0.25 — so a temperature has no parameter that
addresses it.

The numbers show it cleanly. The refitted temperature moves the mean from
0.277 to **0.497**, so it has centred the distribution; and
**accuracy at p=0.5 does not move at all**, staying at 0.116. It flattened
everything toward indifference, which improves ECE while leaving every
decision exactly as wrong as before.

A Platt rescaling has the bias term a shift needs, and it uses it — to move
the whole distribution onto the prior.

## 4. Perfect calibration, no information

| | Platt refit | a constant predictor at the base rate |
|---|---|---|
| ECE | 0.0083 | ~0 |
| Brier | 0.0563 | 0.0564 |
| accuracy @ p=0.5 | 0.940 | 0.940 |
| mean p | 0.940 | 0.940 |

They are the same arm. The Brier looks excellent only because the base rate is
94% and therefore far from 0.5 — on a balanced population the same collapse
would score 0.25.

`experiments/checks.py` now carries `collapsed_to_prior`, which fails when the
mean probability and the fixed-threshold accuracy both sit at the base rate,
and it fires on this run automatically. **A calibration figure quoted without
that check is not evidence that anything was learned.** That is the
generalisable lesson here, and it would have caught the published-ECE
improvements this experiment was modelled on being read the same way.

## 5. What this settles

**Settles:** recalibration cannot rescue X2, by argument and by measurement.
The two candidate repairs named in X2 §2 and in the registration's §5 are both
now measured and neither works. A typed decision model at this checkpoint does
not carry an abstention signal worth acting on, and the reason is
discrimination — AUC 0.6488 against a lexical score's 0.7113 — not scale.

**Does not settle:** anything about Kev-4B, 9B or 27B, whose published Brier
is roughly half the 0.8B's. The invariance argument says a *refit* of those
checkpoints could not rescue a weak AUC either, but their AUC is unmeasured
and is the thing that would have to be better. That remains blocked on
hardware: 4B needs ~8 GB resident against 3.1 GB free here.

**And one thing worth keeping:** the calibration machinery itself is sound and
cheap. If a future arm *does* discriminate, `x2_recalibrate.py` makes its
probabilities trustworthy at a stated threshold in seconds and with no model
calls, which is what principles 4 and 5 ask for. The order matters, though,
and this result is why: **get the discrimination first.** Calibration is a
transformation of a signal, and transforming a weak signal yields a
well-presented weak signal.
