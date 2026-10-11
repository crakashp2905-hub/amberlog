# relevance_v1 — dev split

- **Arms:** none, lexical, vector, hybrid, current, store_plain, store_vector, store_lexical, store_temporal, store_roots, store_lineage, store_all, oracle
- **Cases:** 15 · **k:** 3
- **Deterministic:** no model calls; two runs of one commit are byte-identical.

## Arms

| arm | nDCG@k | P@k | R@k | MRR | critical recall | critical omission | must-not-expose | irrelevant | abstain precision | false abstain |
|---|---|---|---|---|---|---|---|---|---|---|
| `none` | 0.000 | 0.000 | 0.000 | 0.000 | 0.143 | 0.857 | **0.000** | 0.000 | 1.000 | 1.000 |
| `lexical` | 0.778 | 0.452 | 0.821 | 0.845 | 0.714 | 0.286 | **0.000** | 0.429 | 0.000 | 0.000 |
| `vector` | 0.728 | 0.381 | 0.786 | 0.774 | 0.714 | 0.286 | **0.000** | 0.548 | 0.000 | 0.000 |
| `hybrid` | 0.752 | 0.429 | 0.857 | 0.774 | 0.786 | 0.214 | **0.000** | 0.476 | 0.000 | 0.000 |
| `current` | 0.786 | 0.452 | 0.893 | 0.786 | 0.857 | 0.143 | **0.000** | 0.452 | 0.000 | 0.000 |
| `store_plain` | 0.752 | 0.429 | 0.857 | 0.774 | 0.786 | 0.214 | **0.000** | 0.476 | 0.000 | 0.000 |
| `store_vector` | 0.728 | 0.381 | 0.786 | 0.774 | 0.714 | 0.286 | **0.000** | 0.548 | 0.000 | 0.000 |
| `store_lexical` | 0.756 | 0.452 | 0.821 | 0.798 | 0.714 | 0.286 | **0.000** | 0.429 | 0.000 | 0.000 |
| `store_temporal` | 0.795 | 0.452 | 0.893 | 0.798 | 0.857 | 0.143 | **0.000** | 0.452 | 0.000 | 0.000 |
| `store_roots` | 0.780 | 0.452 | 0.893 | 0.786 | 0.857 | 0.143 | **0.000** | 0.476 | 0.000 | 0.000 |
| `store_lineage` | 0.786 | 0.452 | 0.893 | 0.786 | 0.857 | 0.143 | **0.000** | 0.452 | 0.000 | 0.000 |
| `store_all` | 0.795 | 0.452 | 0.893 | 0.798 | 0.857 | 0.143 | **0.000** | 0.452 | 0.000 | 0.000 |
| `oracle` | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 0.000 | **0.000** | 0.000 | 1.000 | 0.000 |

## Headroom

- Best simple baseline: `store_temporal` at 0.795 ndcg_at_k
- Ceiling (`oracle`): 1.000
- **Headroom: +0.205**

A ranker's threshold is a share of that headroom, never an absolute margin (AGENTS.md principle 8a). The oracle runs through the same gates with the same `k`, so it scores below 1.0 wherever a gate refuses a memory the labels call relevant — correct behaviour, and headroom no ranker may reach (principle 8b).

## By family

### `none`

| family | cases | nDCG | critical recall | violations | abstained |
|---|---|---|---|---|---|
| apparent_conflict | 1 | 0.000 | 0.000 | 0 | 1 |
| conflicting | 1 | 0.000 | 0.000 | 0 | 1 |
| constrained | 1 | 0.000 | 0.000 | 0 | 1 |
| copied_evidence | 1 | 0.000 | 0.000 | 0 | 1 |
| direct | 1 | 0.000 | 0.000 | 0 | 1 |
| indirect | 1 | 0.000 | 0.000 | 0 | 1 |
| lexical_trap | 1 | 0.000 | 0.000 | 0 | 1 |
| near_duplicate | 1 | 0.000 | 0.000 | 0 | 1 |
| negative_evidence | 1 | 0.000 | 0.000 | 0 | 1 |
| rare_critical | 1 | 0.000 | 0.000 | 0 | 1 |
| retracted | 1 | 0.000 | 1.000 | 0 | 1 |
| superseded | 1 | 0.000 | 0.000 | 0 | 1 |
| temporal_drift | 1 | 0.000 | 0.000 | 0 | 1 |
| unanswerable | 1 | — | — | 0 | 1 |
| unauthorized | 1 | 0.000 | 1.000 | 0 | 1 |

### `lexical`

| family | cases | nDCG | critical recall | violations | abstained |
|---|---|---|---|---|---|
| apparent_conflict | 1 | 0.920 | 1.000 | 0 | 0 |
| conflicting | 1 | 1.000 | 1.000 | 0 | 0 |
| constrained | 1 | 1.000 | 1.000 | 0 | 0 |
| copied_evidence | 1 | 0.613 | 0.000 | 0 | 0 |
| direct | 1 | 1.000 | 1.000 | 0 | 0 |
| indirect | 1 | 0.613 | 0.000 | 0 | 0 |
| lexical_trap | 1 | 0.631 | 1.000 | 0 | 0 |
| near_duplicate | 1 | 0.613 | 0.000 | 0 | 0 |
| negative_evidence | 1 | 1.000 | 1.000 | 0 | 0 |
| rare_critical | 1 | 0.000 | 0.000 | 0 | 0 |
| retracted | 1 | 1.000 | 1.000 | 0 | 0 |
| superseded | 1 | 1.000 | 1.000 | 0 | 0 |
| temporal_drift | 1 | 0.500 | 1.000 | 0 | 0 |
| unanswerable | 1 | — | — | 0 | 0 |
| unauthorized | 1 | 1.000 | 1.000 | 0 | 0 |

### `vector`

| family | cases | nDCG | critical recall | violations | abstained |
|---|---|---|---|---|---|
| apparent_conflict | 1 | 0.920 | 1.000 | 0 | 0 |
| conflicting | 1 | 1.000 | 1.000 | 0 | 0 |
| constrained | 1 | 0.920 | 1.000 | 0 | 0 |
| copied_evidence | 1 | 0.000 | 0.000 | 0 | 0 |
| direct | 1 | 1.000 | 1.000 | 0 | 0 |
| indirect | 1 | 0.613 | 0.000 | 0 | 0 |
| lexical_trap | 1 | 0.631 | 1.000 | 0 | 0 |
| near_duplicate | 1 | 0.000 | 0.000 | 0 | 0 |
| negative_evidence | 1 | 1.000 | 1.000 | 0 | 0 |
| rare_critical | 1 | 0.613 | 0.000 | 0 | 0 |
| retracted | 1 | 1.000 | 1.000 | 0 | 0 |
| superseded | 1 | 1.000 | 1.000 | 0 | 0 |
| temporal_drift | 1 | 0.500 | 1.000 | 0 | 0 |
| unanswerable | 1 | — | — | 0 | 0 |
| unauthorized | 1 | 1.000 | 1.000 | 0 | 0 |

### `hybrid`

| family | cases | nDCG | critical recall | violations | abstained |
|---|---|---|---|---|---|
| apparent_conflict | 1 | 0.920 | 1.000 | 0 | 0 |
| conflicting | 1 | 1.000 | 1.000 | 0 | 0 |
| constrained | 1 | 1.000 | 1.000 | 0 | 0 |
| copied_evidence | 1 | 0.307 | 0.000 | 0 | 0 |
| direct | 1 | 1.000 | 1.000 | 0 | 0 |
| indirect | 1 | 0.613 | 0.000 | 0 | 0 |
| lexical_trap | 1 | 0.500 | 1.000 | 0 | 0 |
| near_duplicate | 1 | 0.307 | 1.000 | 0 | 0 |
| negative_evidence | 1 | 1.000 | 1.000 | 0 | 0 |
| rare_critical | 1 | 0.387 | 0.000 | 0 | 0 |
| retracted | 1 | 1.000 | 1.000 | 0 | 0 |
| superseded | 1 | 1.000 | 1.000 | 0 | 0 |
| temporal_drift | 1 | 0.500 | 1.000 | 0 | 0 |
| unanswerable | 1 | — | — | 0 | 0 |
| unauthorized | 1 | 1.000 | 1.000 | 0 | 0 |

### `current`

| family | cases | nDCG | critical recall | violations | abstained |
|---|---|---|---|---|---|
| apparent_conflict | 1 | 0.920 | 1.000 | 0 | 0 |
| conflicting | 1 | 1.000 | 1.000 | 0 | 0 |
| constrained | 1 | 1.000 | 1.000 | 0 | 0 |
| copied_evidence | 1 | 0.387 | 0.000 | 0 | 0 |
| direct | 1 | 1.000 | 1.000 | 0 | 0 |
| indirect | 1 | 1.000 | 1.000 | 0 | 0 |
| lexical_trap | 1 | 0.500 | 1.000 | 0 | 0 |
| near_duplicate | 1 | 0.307 | 1.000 | 0 | 0 |
| negative_evidence | 1 | 1.000 | 1.000 | 0 | 0 |
| rare_critical | 1 | 0.387 | 0.000 | 0 | 0 |
| retracted | 1 | 1.000 | 1.000 | 0 | 0 |
| superseded | 1 | 1.000 | 1.000 | 0 | 0 |
| temporal_drift | 1 | 0.500 | 1.000 | 0 | 0 |
| unanswerable | 1 | — | — | 0 | 0 |
| unauthorized | 1 | 1.000 | 1.000 | 0 | 0 |

### `store_plain`

| family | cases | nDCG | critical recall | violations | abstained |
|---|---|---|---|---|---|
| apparent_conflict | 1 | 0.920 | 1.000 | 0 | 0 |
| conflicting | 1 | 1.000 | 1.000 | 0 | 0 |
| constrained | 1 | 1.000 | 1.000 | 0 | 0 |
| copied_evidence | 1 | 0.307 | 0.000 | 0 | 0 |
| direct | 1 | 1.000 | 1.000 | 0 | 0 |
| indirect | 1 | 0.613 | 0.000 | 0 | 0 |
| lexical_trap | 1 | 0.500 | 1.000 | 0 | 0 |
| near_duplicate | 1 | 0.307 | 1.000 | 0 | 0 |
| negative_evidence | 1 | 1.000 | 1.000 | 0 | 0 |
| rare_critical | 1 | 0.387 | 0.000 | 0 | 0 |
| retracted | 1 | 1.000 | 1.000 | 0 | 0 |
| superseded | 1 | 1.000 | 1.000 | 0 | 0 |
| temporal_drift | 1 | 0.500 | 1.000 | 0 | 0 |
| unanswerable | 1 | — | — | 0 | 0 |
| unauthorized | 1 | 1.000 | 1.000 | 0 | 0 |

### `store_vector`

| family | cases | nDCG | critical recall | violations | abstained |
|---|---|---|---|---|---|
| apparent_conflict | 1 | 0.920 | 1.000 | 0 | 0 |
| conflicting | 1 | 1.000 | 1.000 | 0 | 0 |
| constrained | 1 | 0.920 | 1.000 | 0 | 0 |
| copied_evidence | 1 | 0.000 | 0.000 | 0 | 0 |
| direct | 1 | 1.000 | 1.000 | 0 | 0 |
| indirect | 1 | 0.613 | 0.000 | 0 | 0 |
| lexical_trap | 1 | 0.631 | 1.000 | 0 | 0 |
| near_duplicate | 1 | 0.000 | 0.000 | 0 | 0 |
| negative_evidence | 1 | 1.000 | 1.000 | 0 | 0 |
| rare_critical | 1 | 0.613 | 0.000 | 0 | 0 |
| retracted | 1 | 1.000 | 1.000 | 0 | 0 |
| superseded | 1 | 1.000 | 1.000 | 0 | 0 |
| temporal_drift | 1 | 0.500 | 1.000 | 0 | 0 |
| unanswerable | 1 | — | — | 0 | 0 |
| unauthorized | 1 | 1.000 | 1.000 | 0 | 0 |

### `store_lexical`

| family | cases | nDCG | critical recall | violations | abstained |
|---|---|---|---|---|---|
| apparent_conflict | 1 | 0.920 | 1.000 | 0 | 0 |
| conflicting | 1 | 1.000 | 1.000 | 0 | 0 |
| constrained | 1 | 1.000 | 1.000 | 0 | 0 |
| copied_evidence | 1 | 0.613 | 0.000 | 0 | 0 |
| direct | 1 | 1.000 | 1.000 | 0 | 0 |
| indirect | 1 | 0.613 | 0.000 | 0 | 0 |
| lexical_trap | 1 | 0.631 | 1.000 | 0 | 0 |
| near_duplicate | 1 | 0.307 | 0.000 | 0 | 0 |
| negative_evidence | 1 | 1.000 | 1.000 | 0 | 0 |
| rare_critical | 1 | 0.000 | 0.000 | 0 | 0 |
| retracted | 1 | 1.000 | 1.000 | 0 | 0 |
| superseded | 1 | 1.000 | 1.000 | 0 | 0 |
| temporal_drift | 1 | 0.500 | 1.000 | 0 | 0 |
| unanswerable | 1 | — | — | 0 | 0 |
| unauthorized | 1 | 1.000 | 1.000 | 0 | 0 |

### `store_temporal`

| family | cases | nDCG | critical recall | violations | abstained |
|---|---|---|---|---|---|
| apparent_conflict | 1 | 0.920 | 1.000 | 0 | 0 |
| conflicting | 1 | 1.000 | 1.000 | 0 | 0 |
| constrained | 1 | 1.000 | 1.000 | 0 | 0 |
| copied_evidence | 1 | 0.387 | 0.000 | 0 | 0 |
| direct | 1 | 1.000 | 1.000 | 0 | 0 |
| indirect | 1 | 1.000 | 1.000 | 0 | 0 |
| lexical_trap | 1 | 0.500 | 1.000 | 0 | 0 |
| near_duplicate | 1 | 0.307 | 1.000 | 0 | 0 |
| negative_evidence | 1 | 1.000 | 1.000 | 0 | 0 |
| rare_critical | 1 | 0.387 | 0.000 | 0 | 0 |
| retracted | 1 | 1.000 | 1.000 | 0 | 0 |
| superseded | 1 | 1.000 | 1.000 | 0 | 0 |
| temporal_drift | 1 | 0.631 | 1.000 | 0 | 0 |
| unanswerable | 1 | — | — | 0 | 0 |
| unauthorized | 1 | 1.000 | 1.000 | 0 | 0 |

### `store_roots`

| family | cases | nDCG | critical recall | violations | abstained |
|---|---|---|---|---|---|
| apparent_conflict | 1 | 0.920 | 1.000 | 0 | 0 |
| conflicting | 1 | 1.000 | 1.000 | 0 | 0 |
| constrained | 1 | 1.000 | 1.000 | 0 | 0 |
| copied_evidence | 1 | 0.693 | 1.000 | 0 | 0 |
| direct | 1 | 1.000 | 1.000 | 0 | 0 |
| indirect | 1 | 0.613 | 0.000 | 0 | 0 |
| lexical_trap | 1 | 0.500 | 1.000 | 0 | 0 |
| near_duplicate | 1 | 0.307 | 1.000 | 0 | 0 |
| negative_evidence | 1 | 1.000 | 1.000 | 0 | 0 |
| rare_critical | 1 | 0.387 | 0.000 | 0 | 0 |
| retracted | 1 | 1.000 | 1.000 | 0 | 0 |
| superseded | 1 | 1.000 | 1.000 | 0 | 0 |
| temporal_drift | 1 | 0.500 | 1.000 | 0 | 0 |
| unanswerable | 1 | — | — | 0 | 0 |
| unauthorized | 1 | 1.000 | 1.000 | 0 | 0 |

### `store_lineage`

| family | cases | nDCG | critical recall | violations | abstained |
|---|---|---|---|---|---|
| apparent_conflict | 1 | 0.920 | 1.000 | 0 | 0 |
| conflicting | 1 | 1.000 | 1.000 | 0 | 0 |
| constrained | 1 | 1.000 | 1.000 | 0 | 0 |
| copied_evidence | 1 | 0.387 | 0.000 | 0 | 0 |
| direct | 1 | 1.000 | 1.000 | 0 | 0 |
| indirect | 1 | 1.000 | 1.000 | 0 | 0 |
| lexical_trap | 1 | 0.500 | 1.000 | 0 | 0 |
| near_duplicate | 1 | 0.307 | 1.000 | 0 | 0 |
| negative_evidence | 1 | 1.000 | 1.000 | 0 | 0 |
| rare_critical | 1 | 0.387 | 0.000 | 0 | 0 |
| retracted | 1 | 1.000 | 1.000 | 0 | 0 |
| superseded | 1 | 1.000 | 1.000 | 0 | 0 |
| temporal_drift | 1 | 0.500 | 1.000 | 0 | 0 |
| unanswerable | 1 | — | — | 0 | 0 |
| unauthorized | 1 | 1.000 | 1.000 | 0 | 0 |

### `store_all`

| family | cases | nDCG | critical recall | violations | abstained |
|---|---|---|---|---|---|
| apparent_conflict | 1 | 0.920 | 1.000 | 0 | 0 |
| conflicting | 1 | 1.000 | 1.000 | 0 | 0 |
| constrained | 1 | 1.000 | 1.000 | 0 | 0 |
| copied_evidence | 1 | 0.387 | 0.000 | 0 | 0 |
| direct | 1 | 1.000 | 1.000 | 0 | 0 |
| indirect | 1 | 1.000 | 1.000 | 0 | 0 |
| lexical_trap | 1 | 0.500 | 1.000 | 0 | 0 |
| near_duplicate | 1 | 0.307 | 1.000 | 0 | 0 |
| negative_evidence | 1 | 1.000 | 1.000 | 0 | 0 |
| rare_critical | 1 | 0.387 | 0.000 | 0 | 0 |
| retracted | 1 | 1.000 | 1.000 | 0 | 0 |
| superseded | 1 | 1.000 | 1.000 | 0 | 0 |
| temporal_drift | 1 | 0.631 | 1.000 | 0 | 0 |
| unanswerable | 1 | — | — | 0 | 0 |
| unauthorized | 1 | 1.000 | 1.000 | 0 | 0 |

### `oracle`

| family | cases | nDCG | critical recall | violations | abstained |
|---|---|---|---|---|---|
| apparent_conflict | 1 | 1.000 | 1.000 | 0 | 0 |
| conflicting | 1 | 1.000 | 1.000 | 0 | 0 |
| constrained | 1 | 1.000 | 1.000 | 0 | 0 |
| copied_evidence | 1 | 1.000 | 1.000 | 0 | 0 |
| direct | 1 | 1.000 | 1.000 | 0 | 0 |
| indirect | 1 | 1.000 | 1.000 | 0 | 0 |
| lexical_trap | 1 | 1.000 | 1.000 | 0 | 0 |
| near_duplicate | 1 | 1.000 | 1.000 | 0 | 0 |
| negative_evidence | 1 | 1.000 | 1.000 | 0 | 0 |
| rare_critical | 1 | 1.000 | 1.000 | 0 | 0 |
| retracted | 1 | 1.000 | 1.000 | 0 | 0 |
| superseded | 1 | 1.000 | 1.000 | 0 | 0 |
| temporal_drift | 1 | 1.000 | 1.000 | 0 | 0 |
| unanswerable | 1 | — | — | 0 | 1 |
| unauthorized | 1 | 1.000 | 1.000 | 0 | 0 |

