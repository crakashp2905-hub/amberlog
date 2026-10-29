# Pre-registration — T1: does trust that learns how fast to forget decide better?

**Registered 2026-10-18, after two dev pilots (seeds 100–102) and before the
test seeds (0–9).** This is the first of the two claims scoped from the
temporal-reasoning review (2026-10-18). Mechanism:
`TransferTrust(adaptive=True)` in `amberlog/trust.py`: a half-life per
context, chosen from {∞, 200, 60, 20} episodes by prequential log score.
Harness: `experiments/t1_staleness.py`, S4's world with uneven drift.

**Disclosed: the first pilot changed the world.** At first the drift redrew
each lesson's validity at unchanged rates. That leaves every sender's
reliability the same in expectation, so there was nothing to forget. The
drift now reshuffles *which sender is reliable* in a context:

- context 0 never changes;
- context 1 is reshuffled every 120 episodes;
- context 2 is reshuffled once, at episode 450.

## Arms and dev baselines (8a–8d, success, second pilot)

| arm | success |
|---|---|
| `trust_none` | 0.502 |
| `sender_value` | 0.508 |
| `trust_cumulative` (S4, no forgetting) | 0.588 |
| `trust_fixed` (half-life 60 episodes) | 0.590 |
| `invalidate_on_contradiction` (Zep-style) | **0.597** (best baseline) |
| `trust_adaptive` (T1) | 0.592 |
| `oracle` | 0.833 |

No baseline maxes the metric, and no arm beats the oracle. The adaptive
learner identified the drifting context, choosing a half-life of 20 for
context 1 on 3 of 3 seeds.

## Hypothesis

**T1.** `trust_adaptive` closes **at least 40%** of the headroom between the
best baseline and the oracle on success. `memeval.Registration`, 10 seeds.

## Predictions

1. **T1 fails.** Dev showed −0.006 against Zep-style invalidation.
2. The adaptive learner picks a short half-life for context 1 and a long one
   or none for context 0 on most seeds. The detection works; the decision
   gain is what is in doubt.
3. Every trust arm beats `trust_none` by more than 0.08. What matters is
   learning *whom* to trust; *how fast to forget* is second order.

## What this would not establish

A simulator, no model, one grain of trust. Forgetting *per lesson* is not
tested.
