# Pre-registration — V1: claim validation against the store's own knowledge

**Registered 2026-10-19, after the dev split (seeds 400–402) and before the
held-out split (500–509).** Harness: `experiments/v1_claim_validation.py`,
deterministic, no model. Mechanism: `memory-fabric/validation.py`.

## Dev (rate flagged suspicious / provisional or worse)

| family | suspicious | provisional+ |
|---|---|---|
| reassert_corrected | 1.000 | 1.000 |
| out_of_range | 1.000 | 1.000 |
| contradict | 1.000 | 1.000 |
| plausible_new | 0.000 | 1.000 |
| honest_new | 0.000 | 0.000 |
| honest_update | 0.000 | 0.000 |
| honest_outlier | 0.067 | 0.067 |
| honest_new_author | 0.033 | 1.000 |
| **honest, false suspicious** | **0.015** | |

**Changed during dev, disclosed.** The first version flagged 10.4% of honest
writes. Two rules changed: (1) an "established" contradicting memory must be
by an author with another usable memory, because an earlier poison counted
as established and honest corrections of it were flagged; (2) an outlier
must be beyond twice the largest or half the smallest comparable value as
well as z > 3.5, because z alone flagged honest values 1.6× the usual top.
The first form of rule (1) missed each author's first memory (contradict
0.80); it now counts the author's record as it stands when the new claim
arrives. Each change is a rule about what the signal means, not a threshold
fitted to the fixture, but all three were made on this split.

## Hypotheses (held-out)

- **V1-D (detection):** suspicious rate ≥ 0.95 for `reassert_corrected`,
  ≥ 0.90 for `out_of_range` and `contradict`.
- **V1-F (false alarms):** suspicious rate over all honest families ≤ 0.05.
- **V1-P (provisional):** `plausible_new` is provisional or worse at ≥ 0.95,
  and `honest_new` (an established author) at ≤ 0.05.

## Predictions, including what it cannot do

1. All three hold.
2. `plausible_new` is never suspicious. A plausible claim about equipment
   the store has never seen, from a source with no record, is
   indistinguishable from a true one. Provisional is the most a store can
   honestly say, and only because the source is new.
3. Not in this world, and not detectable by this mechanism: a compromised
   **established** author changing its own fact (it reads as an honest
   update), and a plausible lie from an established author about new
   equipment.
