# V1 result — claim validation: all three hypotheses SUPPORTED

Registration: [prereg/v1-claim-validation.md](../prereg/v1-claim-validation.md),
written after the dev split. Held-out seeds 500–509, deterministic, no model.
Raw: [registered configuration](v1-claim-validation-test.json),
[shipped configuration](v1-claim-validation-test-shipped.json).

| family | suspicious | provisional or worse | n |
|---|---|---|---|
| reassert_corrected | **1.000** | 1.000 | 80 |
| out_of_range | **1.000** | 1.000 | 100 |
| contradict | **1.000** | 1.000 | 100 |
| plausible_new | 0.000 | **1.000** | 100 |
| honest_new | 0.000 | 0.000 | 200 |
| honest_update | 0.000 | 0.000 | 100 |
| honest_outlier | 0.000 | 0.000 | 50 |
| honest_new_author | 0.000 | 1.000 | 100 |
| **honest, false suspicious** | **0.000** (0 / 450) | | |

- **V1-D (detection): SUPPORTED.** 1.000 on each family, against bars of
  0.95 and 0.90.
- **V1-F (false alarms): SUPPORTED.** 0 of 450 honest writes flagged
  suspicious (bar ≤ 0.05).
- **V1-P (provisional): SUPPORTED.** Every plausible claim from an unknown
  source is provisional (bar ≥ 0.95); no claim from an established author
  about new equipment is (bar ≤ 0.05).
- **Prediction 2 held:** a plausible claim about never-seen equipment is
  never suspicious. Provisional, because the source is new, is all a store
  can honestly say.

## The shipped configuration

The registered run let every write go live. The product now holds a
suspicious write as a candidate (`Amberlog(hold_suspicious=True)`, the
default). Held poisons then drop out of the comparison set for later
writes, which moved one borderline value: **1 of 450 honest writes**
flagged (0.002), a new author's unusual value. Detection is unchanged
(1.000 on all three families).

## What it does not cover, stated in advance and still true

- A plausible, in-range claim about something the store has never seen.
- A compromised **established** author changing its own fact (it reads as
  an honest update).
- The world is the author's own, numeric, and template-worded. Free-text
  claims that `conflicts.claim` cannot parse into identifiers and values
  are not assessed at all (`unremarkable`).

## Product consequence

Shipped: `validation.assess` and `assess_write`; writes that fail are held
for review by default; the action gate refuses suspicious evidence by
default (`ToolRule.refuse_suspicious`); recall marks them `implausible`;
`validation.review_queue` lists them. The index costs about 0.1 ms per write
at 5,000 memories.
