# T1 result — learned staleness: **NOT SUPPORTED**

Registration: [prereg/t1-learned-staleness.md](../prereg/t1-learned-staleness.md).
Run at `f4d2e4a`, seeds 0–9, 900 episodes each, 9,000 paired episodes.
Deterministic, no model. Raw output: [t1-staleness.json](t1-staleness.json).

| arm | success | context 0 (stable) | context 1 (reshuffled every 120) | context 2 (reshuffled once) | harmful reliance |
|---|---|---|---|---|---|
| `trust_none` | 0.501 | 0.498 | 0.498 | 0.506 | 0 |
| `sender_value` | 0.496 | 0.482 | 0.508 | 0.496 | 0.506 |
| `trust_cumulative` (best baseline) | 0.590 | **0.666** | 0.523 | 0.579 | 0.277 |
| `trust_fixed` (half-life 60) | 0.582 | 0.640 | 0.524 | 0.583 | 0.277 |
| `invalidate_on_contradiction` (Zep-style) | 0.587 | 0.637 | **0.540** | 0.584 | **0.262** |
| **`trust_adaptive`** (T1) | **0.593** | 0.662 | 0.534 | 0.582 | 0.274 |
| `oracle` | 0.829 | 0.829 | 0.830 | 0.827 | 0 |

- **T1: NOT SUPPORTED.** The adaptive arm closes **1.5%** of the headroom:
  +0.004 over cumulative trust, CI −0.005 to +0.012, realised MDE 0.012.
- **All three predictions held.**
  1. T1 failed.
  2. **Detection is perfect.** The half-life chosen per context:
     - context 0: none or 200 episodes (10 of 10 seeds);
     - context 1: 20 episodes (10 of 10);
     - context 2: 60 or 20.
  3. Learning *whom* to trust is worth about 0.09. Learning *how fast to
     forget* is worth a few thousandths.

## What was learned

- **A fixed forgetting rate is a trade, and adapting it removes the trade
  without adding anything.**
  - A fixed half-life or Zep-style invalidation helps the drifting context
    (+0.017) and pays for it in the stable one (−0.03).
  - The adaptive learner keeps the stable context near cumulative trust
    (0.662 against 0.666) and takes most of the drifting context's gain
    (0.534 against 0.540).
  - Net: the best arm, and indistinguishable from never forgetting.
- **The bottleneck is not staleness.** Every trust arm sits about 0.24 below
  the oracle. That gap is exploration and the sender-level grain: Thompson
  sampling still relies on bad lessons from a mostly good sender. How fast
  to forget cannot reach that gap.
- **For the temporal-reasoning question,** adaptive forgetting is **not a
  route to beating strong memory systems** in this setting. It is a safe
  default, never worse than the best fixed choice, and it should not be
  claimed as an improvement.
