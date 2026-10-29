# S5 result — correction receipts: **S5b SUPPORTED, S5a NOT SUPPORTED as registered**

Registration: [prereg/s5-correction-receipts.md](../prereg/s5-correction-receipts.md)
(`4161246`). Mechanism: `amberlog/receipts.py`. Run: `python -m
experiments.s5_receipt_leakage --seeds 5` in a worktree pinned at `4161246`.
150 recipients, deterministic, no model. Raw output:
[s5-receipt-leakage.json](s5-receipt-leakage.json). Exploratory replication on
seeds 5–9: [s5-receipt-leakage-replication.json](s5-receipt-leakage-replication.json).

## Results

The best attacker's advantage is accuracy minus the guess-the-commonest
baseline, or R² for activity, leave-one-out over 150 recipients. Its
best-scoring feature is in parentheses.

| attribute | `ack` (today) | `receipt` (S5) | replication, `receipt` |
|---|---|---|---|
| activity between retractions | **0.994** (`state_revision` delta) | 0.000 | 0.000 |
| copies held | **0.640** (`detail`) | **0.113** (commitment's first byte) | 0.053 (tag's first byte) |
| onward peers | **0.707** (`detail`) | 0.000 | 0.000 |
| dependents | −0.007 | 0.000 | 0.000 |

**Soundness: 150/150 on every check.**

- An honest receipt passes audit.
- A forged commitment fails.
- A store that never applied the retraction can neither issue a receipt nor
  pass audit with someone else's.
- A copy re-activated after the receipt is reported.

## Verdicts

- **S5b: SUPPORTED.**
- **S5a: NOT SUPPORTED as registered.** The receipt scores 0.113 on copies
  held, against a 0.05 bar.
- **Validity: holds.** The attack works on `ack`: above 0.4 on activity,
  copies and peers.

## Why S5a failed, measured and not argued

A SHA-256 output byte cannot carry the copy count of its input. But that is
an argument, so it was measured as well, after the run and clearly marked as
exploratory:

- **The registered bar sits inside the statistic's own noise.** I simulated
  500 receipts made of pure random bytes and scored them with the registered
  statistic (the best cell over every attribute and feature). Its median is
  0.033 and its 95th percentile is 0.080. **A receipt carrying no information
  at all fails the registered 0.05 bar 25.6% of the time.**
- **On the copies cell alone the observed 0.113 is extreme:** p = 0.002 under
  a permutation null for that cell. After maximising over the cells the
  statistic takes, it is about a 1-in-100 draw. I cannot separate a rare draw
  from a defect in the scoring with these data. What can be said is that no
  mechanism links the two, and that the replication on fresh seeds gives
  0.053 through a *different* field (the tag, an HMAC of the commitment).
- **The lesson is the one AGENTS.md 8a states for ceilings, applied to
  floors.** A leakage bar has to be set against the statistic's null
  distribution, measured first. The registration set 0.05 by intuition. A
  bar the perfect mechanism fails one time in four is not a bar.

## Predictions

1. *S5a and S5b hold.* **S5b held. S5a did not**, for the reason above.
2. *`ack` leaks activity almost exactly and onward peers, copies only partly,
   dependents not at all.* **Held.**
   - activity R² 0.994;
   - peers +0.707, which is perfect accuracy;
   - copies +0.640 (perfect accuracy from `detail`);
   - dependents about 0.

   "Copies only partly" was wrong: `detail` gives copies exactly.

## What changed

- **A measured leak in today's protocol.** Every acknowledgement tells the
  origin how much the recipient did between two retractions (its log head),
  how many copies it held, and how many stores it re-shared to. Recorded as
  finding F13 in the security review: medium, fixed in `ab3861a` with no
  wire change.
- **F13 is now fixed and re-measured.** The same harness, seeds 0–4, ran at
  `ab3861a`. Today's acknowledgement now scores **0.000 on activity, copies,
  peers and dependents** ([s5-receipt-leakage-after-f13.json](s5-receipt-leakage-after-f13.json)).
  `state_revision` counts the origin's own retractions, and `detail` says only
  "withdrawn".
- **`receipts.py` is the replacement, opt-in.** It is fixed-size, with no
  counts and no sequence. It binds at audit against the recipient's
  hash-chained log, and recomputing the opening needs no new event.

## What this does not establish

- **Timing.** The origin still sees when a receipt arrives.
- **Simple attackers only.** A learned attacker over many receipts is not
  tested. The argument against one is cryptographic.
- **Binding at audit assumes the auditor trusts the chain digest.**
