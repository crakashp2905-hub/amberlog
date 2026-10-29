# Pre-registration — T2: once a source is caught being wrong, does re-reading its other notes help?

**Registered 2026-10-19, after two dev pilots (seed 100) and before the
held-out seeds (10–14).** This is the second claim scoped from the
temporal-reasoning review: the backward one. Mechanism:
`amberlog/hindsight.py`. Harness: `experiments/t2_hindsight.py`, on
G4b's LabNet.

At stage 2 the origin withdraws what has been detected as false, and also
**one honest technician's note, as an honest mistake**. That is the control:
everything else that technician wrote is correct. The question is asked at
stages 2–3, and the mistaken fact is not scored.

**Disclosed, from the dev world before any model call:**

- reading the withdrawal basis alone missed every cross-store withdrawal,
  so both basis and reason are read;
- a note caught by the injection screen counts as discrediting.

**Disclosed, from the first pilot:** the arm `hostile`, which discredits a
source only on the injection-screen signal, was added after the pilot showed
`withhold` losing every collateral fact.

## Dev pilot (qwen2.5:3b, 92 units)

| arm | safe success | attacker's undetected notes | collateral (the honest technician) |
|---|---|---|---|
| `fabric` (best baseline) | 0.794 | 0.125 | 1.000 |
| `fabric_hindsight_flag` | 0.772 | 0.000 | 1.000 |
| `fabric_hindsight_withhold` | 0.609 | 0.563 | **0.000** |
| `fabric_hindsight_hostile` | 0.794 | 0.125 | 1.000 |
| `oracle` | 1.000 | 1.000 | 1.000 |

`hostile` equals `fabric` because the screen's verdict never leaves the
origin store: an injection quarantined at write is never shared.

## Hypotheses (held-out seeds 10–14)

Each of `flag`, `withhold` and `hostile` closes at least 40% of the headroom
on stage 2–3 safe success, over the best baseline.

## Predictions

1. **All three fail.**
2. `withhold` gains on the attacker's undetected notes and loses all
   collateral. It is net negative.
3. `flag` is no better than `fabric`: the model ignores the marker.
4. `hostile` equals `fabric`, because the hostile signal does not cross
   stores.

## Why run it

To publish the cost. Hindsight that discredits a source on any withdrawal
punishes honest mistakes, and this design measures how much.
