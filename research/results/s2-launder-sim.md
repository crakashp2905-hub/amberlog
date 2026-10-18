# S2 result — is a second report a second source? **NOT SUPPORTED**

Registration: [prereg/s2-evidence-independence.md](../prereg/s2-evidence-independence.md)
(`1b97588`, written after a disclosed dev run). Mechanism:
`memory_fabric/independence.py`. Run: `python -m experiments.s2_launder_sim
--split test --tau overlap@0.9` in a worktree pinned at `1b97588`. Seeds 0–19,
420 clusters, deterministic, no model. Raw output:
[s2-launder-sim.json](s2-launder-sim.json); dev:
[s2-launder-sim-dev.json](s2-launder-sim-dev.json).

**Verdict: NOT SUPPORTED.** `exposure` closes **28%** of the headroom over the
best baseline, against a registered 40%. It gains **+0.102** decision accuracy
(paired 95% CI +0.045 to +0.160) over a tuned near-duplicate store, and it is
the largest gain any arm makes. But the registered bar was 0.780 and it reached
0.736. The realised MDE was 0.086, so the test could detect the effect it was
looking for, and this is a miss rather than an underpowered result.

## Results (test, 420 clusters)

| arm | decision accuracy | false corroboration | blocked independent |
|---|---|---|---|
| `count_all` | 0.571 | 1.000 | 0.000 |
| `provenance` (the product as shipped) | 0.605 | 0.922 | 0.000 |
| `similarity` (overlap@0.9, tuned on dev) | 0.633 | 0.828 | 0.021 |
| **`exposure`** (S2) | **0.736** | **0.283** | **0.250** |
| `oracle` | 1.000 | 0 | 0 |

Per family (the share of clusters decided correctly):

| family | true sources | count_all | provenance | similarity | exposure |
|---|---|---|---|---|---|
| `laundering_local` | 1 | 0.00 | 0.08 | 0.08 | **1.00** |
| `laundering_cross_store` | 1 | 0.00 | 0.00 | 0.23 | **1.00** |
| `collusion` | 1 | 0.00 | 0.15 | 0.20 | 0.15 |
| `independent_similar` | 2 | 1.00 | 1.00 | 0.98 | 1.00 |
| `independent_cross_store` | 2 | 1.00 | 1.00 | 0.98 | 1.00 |
| `exposed_but_independent` | 2 | 1.00 | 1.00 | 0.97 | **0.00** |
| `independent_plus_copy` | 2 | 1.00 | 1.00 | 0.98 | 1.00 |

No arm beats the oracle. Dev and test agree to within 0.02 on every arm.

## Predictions: all four held

1. *Not supported at 40%.* **Held**: 28%. Dev showed 27%.
2. *Every error is `exposed_but_independent` (0) or `collusion` (only the
   verbatim copies).* **Held**: 0.00, and 0.15, which is exactly
   `provenance`'s score on collusion.
3. *Perfect on both laundering families, where every baseline is at or below
   0.27.* **Held**: 1.00 against at most 0.23.
4. *`similarity` blocks some real corroboration and cannot reach summaries.*
   **Held**: it blocks 2.1% and catches 8% of local laundering.

## What was learned

- **Exposure is the only signal here that catches laundering at all.** False
  corroboration falls from 0.83 to 0.28, and on the laundering families from
  near zero to perfect. This holds across a store boundary too, because the
  dependency travels with the share. Wording-based deduplication tuned to its
  best does almost nothing: a summary shares no details with its source, and a
  reworded copy shares too few at any threshold that spares real reports.
- **The price is exact and structural.** Every exposed author is treated as a
  copier, so `exposed_but_independent` scores 0. The verdict is therefore a
  statement about the case mix as much as about the mechanism: it lost by
  1 family in 7. In a deployment where agents often read before they
  observe, it would block a lot of real corroboration. Where laundering is
  the threat, it removes most false corroboration. The registration said in
  advance that a deployment's mix is unknown.
- **Collusion outside the store is invisible to it**, as it is to every
  mechanism that reads only the store.
- **Not wired into retrieval or the firewall.** AGENTS.md principle 9 applies:
  the measured trade (−0.55 false corroboration, +0.23 blocked independent)
  is a policy choice, not a free improvement. It is available as
  `independent_sources()` for a caller that has made that choice.
- **What a follow-up would need.** The registration declined to register a
  rule that keeps an exposed author's report when it adds new specifics,
  because a launderer can fabricate specifics. Testing one fairly would need a
  launderer that does exactly that.

## What this does not establish

Template texts, so the similarity baseline's numbers depend on my rewordings.
The mechanism's numbers depend only on the case mix. There is no model and no
real agent behaviour.
