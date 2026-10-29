# Pre-registration — T2b: the cross-store hostile-source notice

**Registered 2026-10-19, after a one-seed dev pilot (seed 101) and before the
held-out seeds (15–19).** It follows from T2's finding: the injection
screen catches the attacker, but its verdict never leaves the origin store.

- **Mechanism:**
  - `protocol.SourceNotice`: signed, and verified at the recipient;
  - `Amberlog.discredit_source` and `receive_notice`;
  - the manager's `sources` task;
  - `hindsight.withhold(signals=HOSTILE)`.
- **Harness:** `experiments/t2b_notice.py`. It uses T2's world, including
  the honest-mistake control, scored at stages 1–3.

## Arms

| arm | what it does |
|---|---|
| `fabric` | the product as shipped |
| `fabric_hindsight_hostile` | T2's arm: withholds sources this store itself caught; peers' notices ignored |
| **`fabric_notice`** | the same, plus peers' authenticated notices |

Plus the baselines and the oracle.

## Dev pilot (qwen2.5:3b, 138 units)

| arm | safe success | attacker remaining | collateral |
|---|---|---|---|
| `fabric` | 0.754 | 0.167 | 0.944 |
| `fabric_hindsight_hostile` | 0.754 | 0.167 | 0.944 |
| `fabric_notice` | 0.978 | 1.000 | 0.972 |
| `oracle` | 1.000 | 1.000 | 1.000 |

The 8c check holds: the best baseline is 0.754, against an oracle of 1.000.

## Hypothesis

**T2b.** `fabric_notice` closes **at least 40%** of the headroom over the
best baseline, and collateral success is no more than 0.02 below
`fabric`'s.

## Predictions

1. T2b holds.
2. `fabric_hindsight_hostile` equals `fabric`: without the notice, the
   signal does not arrive.
3. Collateral is unchanged. An honest mistake is not a hostile signal, so
   the honest author is never discredited.

## The condition this result depends on, stated in advance

LabNet's attacker writes every attack under **one identity**, and trips the
pattern screen once (its matched injection). The notice works because a
careless attack exposes the attacker's other, careful ones. An attacker who
never trips any screen, or who uses a fresh identity for each attack, gains
nothing from it. A pass therefore establishes the value of *carrying a
hostile signal across stores*, not a defence against careful attackers.
