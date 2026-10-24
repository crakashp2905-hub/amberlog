# Pre-registration: GME matrix v2 (repaired metrics, restatement contesting)

**Registered after the pilot (seed 0, arms A, B, oracle) and before any
method arm ran under metric v2.** Harness: `experiments/gme_matrix.py`
(`metric_version: 2`). Evaluation seeds **11–15** (never run before).
Follows [gme-matrix.md](gme-matrix.md) and its result
([../results/gme-matrix.md](../results/gme-matrix.md)).

## What changed since v1

1. **Product:** correcting a fact, or withdrawing it as contradicted, now
   contests other notes that state the same claim with the old value
   (`validation.restatements`; `contest_restatements=True` by default). This
   targets v1's H1 failure.
2. **Leak metric:** a value counts only as a stated quantity (number then
   unit). v1 counted "store room 14" as a leak of a proposal of 14.
3. **Compression is measured where it can show:** at a budget of **400**
   tokens, which does not bind for the governed arms, as well as at 60. v1's
   H2 could not pass: under a binding budget every arm fills it.

## Pilot (seed 0), metric v2

| budget | arm | accuracy | stale leak | branch leak (ph. 1) | tokens |
|---|---|---|---|---|---|
| 60 | B | 0.556 | 0.333 | 0.278 | 56.8 |
| 60 | oracle | 1.000 | 0.000 | 0.000 | 13.9 |
| 400 | B | 0.556 | 0.333 | 0.278 | 289.5 |
| 400 | oracle | 1.000 | 0.000 | 0.000 | 13.9 |

Headroom over B is 0.444 at both budgets; B does not max the metric (8c).

## Hypotheses (thresholds as shares of per-seed headroom; seeds 11–15)

- **H1′ (governance, budget 60).** C captures ≥ 0.50 of the headroom over B,
  and C's stale leak ≤ 0.02 and branch leak = 0 **on every seed**.
- **H2′ (compression, budget 400).** E's tokens ≤ 0.80 × C's, and E's share
  is no more than 0.05 below C's.
- **H3′ (merge, budget 60).** G captures ≥ 0.50 of the headroom over F,
  with no resurrection and no lost update on every seed.

No prediction is made for H2′: restatements, the only thing extractive-v2
compresses, are now mostly contested, which may remove the savings.
`any_arm_beats_oracle` must be empty on every run (8b). Output:
`research/results/gme-matrix-v2-b60.json` and `-b400.json`.
