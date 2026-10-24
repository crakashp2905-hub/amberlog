# T2 result — hindsight re-decision: **NOT SUPPORTED** on every arm, all predictions held

Registration: [prereg/t2-hindsight.md](../prereg/t2-hindsight.md). Run at
`fa53a46`, on held-out seeds 10–14, with qwen2.5:3b. Stages 2–3, 460 paired
units. Raw output: [t2-hindsight.json](t2-hindsight.json).

| arm | safe success | acted on invalid | attacker's undetected notes | collateral (honest technician) | other |
|---|---|---|---|---|---|
| `shared_store` | 0.417 | 0.570 | 0.000 | 0.519 | 0.500 |
| `shared_delete_all` | 0.587 | 0.409 | 0.000 | 0.741 | 0.699 |
| `fabric` (best baseline) | **0.783** | 0.215 | 0.050 | 0.917 | 0.945 |
| `fabric_hindsight_flag` | 0.776 | 0.224 | 0.025 | 0.917 | 0.941 |
| `fabric_hindsight_withhold` | 0.672 | **0.089** | **0.500** | **0.120** | 0.941 |
| `fabric_hindsight_hostile` | 0.780 | 0.220 | 0.050 | 0.917 | 0.941 |
| `oracle` | 1.000 | 0 | 1.000 | 1.000 | 1.000 |

Difference from `fabric`, by arm:

| arm | difference | 95% CI |
|---|---|---|
| `flag` | −0.007 | −0.015 to 0.000 |
| `withhold` | −0.111 | −0.157 to −0.063 |
| `hostile` | −0.002 | −0.007 to 0.000 |

All three are NOT SUPPORTED.

## Predictions: all four held

1. All three arms fail.
2. `withhold` gains on the attacker and loses the collateral. The attacker's
   undetected notes go from 0.05 to **0.50**, and the attacker is acted on
   least overall (8.9%). But the honest technician's valid notes fall from
   0.92 to **0.12**, which is net −0.11.
3. `flag` is no better than `fabric`. The model ignores "this source was
   wrong before".
4. `hostile` equals `fabric`. The injection screen's verdict stays at the
   origin store.

## What was learned

- **Hindsight about sources is a sharp trade, not a free improvement.**
  Withholding a discredited source's other notes removes most of what an
  attacker still has in play. It also silences every honest author who has
  ever made one mistake. Discrediting on "a memory was withdrawn as false"
  cannot tell an attacker from a colleague who was wrong once.
- **The useful signal exists but does not travel.** The injection screen
  *does* catch this attacker. Its verdict is a quarantine at the origin store
  that is never shared, so the stores answering questions never learn the
  source is hostile. That is a concrete protocol gap: a federated
  "source discredited" notice would carry exactly the signal that separates
  hostility from honest error. It is not built, and it needs a design
  decision.
- **For the temporal-reasoning question,** neither direction beats the
  strong baseline in our setting:
  - forward (T1): learned forgetting, +0.004;
  - backward (T2): hindsight, flat or negative.

  Strong governance (retraction plus contradiction surfacing) is already
  doing what "temporal reasoning" was meant to add. The one idea with
  measured headroom is cross-store source reputation, and that is a federation
  feature, not a temporal one.
