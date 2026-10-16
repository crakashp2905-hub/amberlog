# P2b — sufficiency at a fixed 400-token budget

Registered in [p2b-sufficiency-at-budget.md](../prereg/p2b-sufficiency-at-budget.md)
(Amendment 1 names the arm and the split). Produced by
`python -m experiments.p2b_budget` at commit `d3d363c`; raw numbers in
[p2b-budget.json](p2b-budget.json).

**SUPPORTED.** On the fresh holdout (66 cases), `chain@400`
reaches 0.700 against B = 0.600 (best of `top_k@400` and `random@400`)
and the oracle's 0.800: threshold 0.680, 50% of the headroom
closed. Arms above the ceiling: none. Non-compliant
(over budget, excluded from B): full_context.
Must-not-expose: zero for every arm.

## Holdout (evaluation)

| arm | sufficient | mean tokens | abstention precision | false abstention | must-not-expose |
|---|---|---|---|---|---|
| `top_k` | 0.600 | 395 | 0.000 | 0.000 | 0.000 |
| `random` | 0.047 | 395 | 0.000 | 0.000 | 0.000 |
| `sufficiency_aware` | 0.433 | 28 | 0.000 | 0.021 | 0.000 |
| `chain` | 0.700 | 395 | 0.000 | 0.000 | 0.000 |
| `oracle_evidence` | 0.800 | 15 | 1.000 | 0.000 | 0.000 |
| `full_context` | 0.800 | 6298 | 0.000 | 0.000 | 0.000 |

`random@400` by seed: 0.050, 0.067, 0.050, 0.067, 0.000.

Sufficiency by family on the holdout:

| family | top_k | random | sufficiency_aware | chain | oracle_evidence | full_context |
|---|---|---|---|---|---|---|
| direct | 1.00 | 0.17 | 0.83 | 1.00 | 1.00 | 1.00 |
| facet_trap | 1.00 | 0.07 | 0.50 | 1.00 | 1.00 | 1.00 |
| multi_hop_3 | 0.00 | 0.00 | 0.00 | 1.00 | 1.00 | 1.00 |
| multi_hop_4 | 0.00 | 0.00 | 0.00 | 0.00 | 1.00 | 1.00 |
| superseded_rev | 1.00 | 0.13 | 0.67 | 1.00 | 1.00 | 1.00 |
| unanswerable | — | nan | — | — | — | — |
| conflicting | 1.00 | 0.00 | 0.33 | 1.00 | 1.00 | 1.00 |
| gated | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 |
| shared_root | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 |
| independent_support | 1.00 | 0.10 | 1.00 | 1.00 | 1.00 | 1.00 |
| budget_pressure | 1.00 | 0.00 | 1.00 | 1.00 | 1.00 | 1.00 |

## dev (for comparison)

| arm | sufficient | mean tokens | abstention precision | false abstention | must-not-expose |
|---|---|---|---|---|---|
| `top_k` | 0.600 | 396 | 0.000 | 0.000 | 0.000 |
| `random` | 0.033 | 395 | 0.000 | 0.000 | 0.000 |
| `sufficiency_aware` | 0.533 | 29 | 0.000 | 0.042 | 0.000 |
| `chain` | 0.700 | 396 | 0.000 | 0.000 | 0.000 |
| `oracle_evidence` | 0.800 | 16 | 1.000 | 0.000 | 0.000 |
| `full_context` | 0.800 | 6337 | 0.000 | 0.000 | 0.000 |

## test, *contaminated* (not evidence)

| arm | sufficient | mean tokens | abstention precision | false abstention | must-not-expose |
|---|---|---|---|---|---|
| `top_k` | 0.600 | 395 | 0.000 | 0.000 | 0.000 |
| `random` | 0.033 | 395 | 0.000 | 0.000 | 0.000 |
| `sufficiency_aware` | 0.500 | 32 | 0.000 | 0.000 | 0.000 |
| `chain` | 0.700 | 395 | 0.000 | 0.000 | 0.000 |
| `oracle_evidence` | 0.800 | 15 | 1.000 | 0.000 | 0.000 |
| `full_context` | 0.800 | 6332 | 0.000 | 0.000 | 0.000 |

P1 inspected the test split when the chain was designed, so it is printed only
so it is not hidden.

**What this does not establish.** The holdout is new cases from the same
templates, not a new distribution. Sufficiency is defined by requirement slots
written by this project. Nothing here is downstream: whether a sufficient
context changes a model's answer is D1's and R6's question.

## Reading (written after the run)

The harness file is unchanged since `7d71b12`, which was committed before the
run. `d3d363c` is the head the run finished at.

**The pass is one family, and it is narrow.** Each family scores 0 or 1 on
every one of its cases, so the pooled rate counts families, not a
distribution. `chain@400` moves exactly one family, `multi_hop_3`, from 0 to
1. That adds +0.100 and clears the threshold of 0.680 by 0.020. All three
splits give the same 0.600 / 0.700 / 0.800, because the templates fix the
outcome per family. The agreement is therefore not independent replication,
and a bootstrap interval over these cases would mean nothing.

**Predictions.**
- (1) `random@400` scores well above zero: **wrong.** It scores 0.047, so at
  this budget a random 38 of about 495 memories almost never holds the
  answer, and ranking carries nearly all of top-k's value.
- (2) top-k does not gain from more budget: consistent with the sweep.
- (3) Any gain is on the multi-hop families only: **right**, and on only one
  of them.
- (4) Abstention stays at 0.000: **right.** No arm abstains on `unanswerable`.

**What is left.**
- `multi_hop_4` is still 0 for every non-oracle arm. `reconstruct(k = 5)`
  returns a chain that misses a hop there.
- `gated` and `shared_root` are 0 even for the oracle under the gates. That is
  a property of how the benchmark scores those families, and has nothing to
  do with budget.
- `sufficiency_aware`, unchanged, is worse than top-k at the same budget
  (0.433), and its §6 defect stands.
