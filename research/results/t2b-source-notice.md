# T2b result — the cross-store hostile-source notice: **SUPPORTED**, all three predictions held

Registration: [prereg/t2b-source-notice.md](../prereg/t2b-source-notice.md),
written after a one-seed dev pilot and before these seeds. Run at `ef928ae`
on held-out seeds 15–19 with qwen2.5:3b, stages 1–3, 690 paired units, in
54 minutes. Raw output: [t2b-source-notice.json](t2b-source-notice.json).

| arm | safe success | acted on invalid | attacker's undetected notes withheld | collateral (honest technician) | other |
|---|---|---|---|---|---|
| `no_memory` | 0.009 | 0.013 | 0.000 | 0.019 | 0.007 |
| `shared_store` | 0.465 | 0.530 | 0.092 | 0.537 | 0.547 |
| `shared_delete_all` | 0.567 | 0.432 | 0.092 | 0.661 | 0.669 |
| `fabric` (best baseline) | **0.732** | 0.268 | 0.192 | 0.803 | 0.863 |
| `fabric_hindsight_hostile` | 0.730 | 0.270 | 0.192 | 0.796 | 0.863 |
| **`fabric_notice`** | **0.949** | **0.051** | **1.000** | **0.914** | 0.949 |
| `oracle` | 1.000 | 0.000 | 1.000 | 1.000 | 1.000 |

**Verdict.** The headroom over the best baseline is 0.268. `fabric_notice`
closes 0.217 of it (95% CI 0.187 to 0.249), which is **81%** against a
registered bar of 40% (0.839). The realised minimum detectable effect is
0.051. No arm beats the oracle (8b).

## Predictions

1. **T2b holds.** It does: 0.949 against a bar of 0.839.
2. **`fabric_hindsight_hostile` equals `fabric`.** It does (0.730 against
   0.732). Without the notice, the recipient never hears the origin's
   verdict.
3. **Collateral is unchanged or better.** It is better: 0.914 against
   0.803. The honest technician is never discredited, because an honest
   mistake is not a hostile signal. The gain over `fabric` comes from the
   attacker's notes no longer crowding the technician's out.

## What it does and does not establish

It establishes that **carrying a hostile verdict across stores** is worth
most of the remaining headroom on LabNet, at no cost to honest sources.

It does not establish a defence against a careful attacker. The registration
stated the dependency in advance: LabNet's attacker writes under one
identity and trips the pattern screen once. An attacker who never trips a
screen, or who uses a fresh identity per attack, gains nothing from the
notice and loses nothing either. Against that attacker, contradiction
surfacing (G4b) and origin-bound authority at the action gate are the
remaining defences.

## Product consequence

**Delivery is on by default.** `SourceNotice`, `/federation/notice` and the
manager's `sources` task run wherever the manager runs with peers, and the
recipient records each authenticated notice.

**Acting on it is not yet a default.** The measured arm applied
`hindsight.withhold(signals=HOSTILE)` to what the recipient retrieves. In
the product that is still a call the host makes, because `hindsight.py` is
experimental. Making the hostile-only withhold the default in retrieval is
the owner's decision: this result supports it, and T2 measured that the
broader withhold (any withdrawal) must stay off.
