# C2-r — decision dependence re-run under the fix (C2 Amendment 1)

Registered in [c2-decision-dependence.md](../prereg/c2-decision-dependence.md) before the
mechanism existed. Produced by `python -m experiments.c2_dependence` at commit `c1cb38b`;
raw numbers in [c2r-dependence.json](c2r-dependence.json). Deterministic, seeds (6, 7, 8, 9, 10),
60 allowed actions a seed, 40 facts with copies and derived conclusions; the most-used
fact is corrected.

**C2a (no dependent action missed): SUPPORTED. C2b (review load): SUPPORTED** —
counterfactual precision 1.000 against graph 0.356 (bar 0.614).

| seed | actions touched | truly depended | graph: flagged · precision · recall | counterfactual: flagged · precision · recall |
|---|---|---|---|---|
| 6 | 8 | 3 | 8 · 0.38 · 1.00 | 3 · 1.00 · 1.00 |
| 7 | 8 | 3 | 8 · 0.38 · 1.00 | 3 · 1.00 · 1.00 |
| 8 | 9 | 3 | 9 · 0.33 · 1.00 | 3 · 1.00 · 1.00 |
| 9 | 8 | 1 | 8 · 0.12 · 1.00 | 1 · 1.00 · 1.00 |
| 10 | 7 | 4 | 7 · 0.57 · 1.00 | 4 · 1.00 · 1.00 |

## Reading

**Both registered claims are supported on fresh seeds once the independence
defect is fixed.** No decision that genuinely depended on the corrected
memory was missed (recall 1.000 on every seed). The review queue shrank from
the graph's list, where 36% of flagged actions truly depended, to exactly the
dependent ones (precision 1.000). In this world, about two in three actions
touched by a correction had independent support and did not need review.

"Depended" here means the recorded evidence would no longer meet the
recorded policy. Whether the agent's reasoning used the memory is a separate
question, which `decisions_depending_on(replay=...)` lets a caller answer by
re-running the agent.
