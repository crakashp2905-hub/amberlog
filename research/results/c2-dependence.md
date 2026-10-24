# C2 — which decisions genuinely depended on a corrected memory?

Registered in [c2-decision-dependence.md](../prereg/c2-decision-dependence.md) before the
mechanism existed. Produced by `python -m experiments.c2_dependence` at commit `0bdb2c3`;
raw numbers in [c2-dependence.json](c2-dependence.json). Deterministic, seeds 1–5,
60 allowed actions a seed, 40 facts with copies and derived conclusions; the most-used
fact is corrected.

**C2a (no dependent action missed): NOT SUPPORTED. C2b (review load): SUPPORTED** —
counterfactual precision 1.000 against graph 0.426 (bar 0.655).

| seed | actions touched | truly depended | graph: flagged · precision · recall | counterfactual: flagged · precision · recall |
|---|---|---|---|---|
| 1 | 6 | 3 | 6 · 0.50 · 1.00 | 1 · 1.00 · 0.33 |
| 2 | 7 | 3 | 7 · 0.43 · 1.00 | 3 · 1.00 · 1.00 |
| 3 | 8 | 5 | 8 · 0.62 · 1.00 | 2 · 1.00 · 0.40 |
| 4 | 10 | 2 | 10 · 0.20 · 1.00 | 1 · 1.00 · 0.50 |
| 5 | 8 | 3 | 8 · 0.38 · 1.00 | 2 · 1.00 · 0.67 |

## Reading (written after the run)

**C2a NOT SUPPORTED as registered: the counterfactual missed dependent
decisions** (recall 0.33–1.00 by seed), while flagging nothing spurious
(precision 1.000 against the graph's 0.426). Every miss had the same cause,
and it was a **product defect**, not a defect of the counterfactual. Asking
for `min_independent_sources=2`, on a certificate *or* on a `ToolRule`, was
enforced only when `independent_support` was also listed among the required
checks. The counterfactual re-certified one remaining source under "need 2",
and the verifier accepted it. The same hole let the action gate allow a
single-source certificate on a tool whose rule demanded two independent
sources, so the corroboration defence that LIMITATIONS recommends did
nothing. Fixed in `certificates.py`, with a regression test
(`test_min_sources_enforced.py`, which fails without the fix). The result
above stands. A re-run under the fix is registered as Amendment 1 on fresh
seeds.
