# L1 — a long-running task: a plain vector store against Memory Fabric

Registered in [l1-long-running-task.md](../prereg/l1-long-running-task.md) before the
harness existed. Produced by `python -m experiments.l1_long_running` at commit
`9c689b3`; raw numbers in [l1-long-running.json](l1-long-running.json). Deterministic,
seeds (1, 2, 3, 4, 5): 600 jobs, 40 pieces of equipment, 16 corrections,
four worker agents writing working notes at rate 0.35.

Best baseline: `vector_append`. Ceiling check: ok.
ABANDONED (8c: a baseline is already at the oracle)

| arm | harmful actions per 1,000 | completion | mean recovery (steps) | actions |
|---|---|---|---|---|
| `oracle` | 0.0 | 1.000 | 0.0 | 600 |
| `vector_append` | 0.0 | 1.000 | 0.0 | 600 |
| `vector_replace` | 0.0 | 1.000 | 0.0 | 600 |

| | L1a harm ≤ 50% of best baseline, all seeds | L1b completion within 5 points | L1c faster recovery, ≥ 4 of 5 seeds |
|---|---|---|---|
| `fabric` | n/a | n/a | n/a |
| `fabric_no_lineage` (no claim registered) | n/a | n/a | n/a |

Harm per 1,000 actions, by seed:

| seed | oracle | vector_append | vector_replace |
|---|---|---|---|
| 1 | 0.0 | 0.0 | 0.0 |
| 2 | 0.0 | 0.0 | 0.0 |
| 3 | 0.0 | 0.0 | 0.0 |
| 4 | 0.0 | 0.0 | 0.0 |
| 5 | 0.0 | 0.0 | 0.0 |
