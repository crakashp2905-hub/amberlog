# relevance_v1 — test split

- **Arms:** none, lexical, vector, hybrid, current, oracle
- **Cases:** 5 · **k:** 3
- **Deterministic:** no model calls; two runs of one commit are byte-identical.

## Arms

| arm | nDCG@k | P@k | R@k | MRR | critical recall | critical omission | must-not-expose | irrelevant | abstain precision | false abstain |
|---|---|---|---|---|---|---|---|---|---|---|
| `none` | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 1.000 | **0.000** | 0.000 | 1.000 | 1.000 |
| `lexical` | 0.804 | 0.500 | 0.900 | 0.800 | 0.800 | 0.200 | **0.000** | 0.433 | 1.000 | 0.000 |
| `vector` | 0.485 | 0.333 | 0.667 | 0.500 | 0.700 | 0.400 | **0.000** | 0.667 | 1.000 | 0.000 |
| `hybrid` | 0.732 | 0.467 | 0.933 | 0.700 | 1.000 | 0.000 | **0.000** | 0.533 | 1.000 | 0.000 |
| `current` | 0.485 | 0.333 | 0.667 | 0.500 | 0.700 | 0.400 | **0.000** | 0.667 | 1.000 | 0.000 |
| `oracle` | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 0.000 | **0.000** | 0.000 | 1.000 | 0.000 |

## Headroom

- Best simple baseline: `lexical` at 0.804 ndcg_at_k
- Ceiling (`oracle`): 1.000
- **Headroom: +0.196**

A ranker's threshold is a share of that headroom, never an absolute margin (AGENTS.md principle 8a). The oracle runs through the same gates with the same `k`, so it scores below 1.0 wherever a gate refuses a memory the labels call relevant — correct behaviour, and headroom no ranker may reach (principle 8b).

## By family

### `none`

| family | cases | nDCG | critical recall | violations | abstained |
|---|---|---|---|---|---|
| direct | 1 | 0.000 | 0.000 | 0 | 1 |
| indirect | 1 | 0.000 | 0.000 | 0 | 1 |
| lexical_trap | 1 | 0.000 | 0.000 | 0 | 1 |
| rare_critical | 1 | 0.000 | 0.000 | 0 | 1 |
| temporal_drift | 1 | 0.000 | 0.000 | 0 | 1 |

### `lexical`

| family | cases | nDCG | critical recall | violations | abstained |
|---|---|---|---|---|---|
| direct | 1 | 1.000 | 1.000 | 0 | 0 |
| indirect | 1 | 1.000 | 1.000 | 0 | 0 |
| lexical_trap | 1 | 1.000 | 1.000 | 0 | 0 |
| rare_critical | 1 | 0.387 | 0.000 | 0 | 0 |
| temporal_drift | 1 | 0.631 | 1.000 | 0 | 0 |

### `vector`

| family | cases | nDCG | critical recall | violations | abstained |
|---|---|---|---|---|---|
| direct | 1 | 0.631 | 1.000 | 0 | 0 |
| indirect | 1 | 0.469 | 0.500 | 0 | 0 |
| lexical_trap | 1 | 0.000 | 0.000 | 0 | 0 |
| rare_critical | 1 | 0.693 | 1.000 | 0 | 0 |
| temporal_drift | 1 | 0.631 | 1.000 | 0 | 0 |

### `hybrid`

| family | cases | nDCG | critical recall | violations | abstained |
|---|---|---|---|---|---|
| direct | 1 | 1.000 | 1.000 | 0 | 0 |
| indirect | 1 | 0.704 | 1.000 | 0 | 0 |
| lexical_trap | 1 | 0.631 | 1.000 | 0 | 0 |
| rare_critical | 1 | 0.693 | 1.000 | 0 | 0 |
| temporal_drift | 1 | 0.631 | 1.000 | 0 | 0 |

### `current`

| family | cases | nDCG | critical recall | violations | abstained |
|---|---|---|---|---|---|
| direct | 1 | 0.631 | 1.000 | 0 | 0 |
| indirect | 1 | 0.469 | 0.500 | 0 | 0 |
| lexical_trap | 1 | 0.000 | 0.000 | 0 | 0 |
| rare_critical | 1 | 0.693 | 1.000 | 0 | 0 |
| temporal_drift | 1 | 0.631 | 1.000 | 0 | 0 |

### `oracle`

| family | cases | nDCG | critical recall | violations | abstained |
|---|---|---|---|---|---|
| direct | 1 | 1.000 | 1.000 | 0 | 0 |
| indirect | 1 | 1.000 | 1.000 | 0 | 0 |
| lexical_trap | 1 | 1.000 | 1.000 | 0 | 0 |
| rare_critical | 1 | 1.000 | 1.000 | 0 | 0 |
| temporal_drift | 1 | 1.000 | 1.000 | 0 | 0 |

