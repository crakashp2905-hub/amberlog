# L1 — a long-running task: a plain vector store against Amberlog

Registered in [l1-long-running-task.md](../prereg/l1-long-running-task.md) before the
harness existed. Amendment 1 (L1′): recall in the words of the job, fresh seeds. Produced by `python -m experiments.l1_long_running --amended` at commit
`9c689b3`; raw numbers in [l1p-long-running.json](l1p-long-running.json). Deterministic,
seeds (6, 7, 8, 9, 10): 600 jobs, 40 pieces of equipment, 16 corrections,
four worker agents writing working notes at rate 0.35.

Best baseline: `vector_replace`. Ceiling check: ok.


| arm | harmful actions per 1,000 | completion | mean recovery (steps) | actions |
|---|---|---|---|---|
| `oracle` | 0.0 | 1.000 | 0.0 | 600 |
| `vector_append` | 88.3 | 0.857 | 136.5 | 564 |
| `vector_replace` | 80.5 | 0.873 | 130.2 | 570 |
| `fabric` | 0.0 | 0.894 | 0.0 | 536 |
| `fabric_no_lineage` | 0.0 | 0.946 | 0.0 | 567 |

| | L1a harm ≤ 50% of best baseline, all seeds | L1b completion within 5 points | L1c faster recovery, ≥ 4 of 5 seeds |
|---|---|---|---|
| `fabric` | pass | pass | pass |
| `fabric_no_lineage` (no claim registered) | pass | pass | pass |

**Reading.** Completion counts a job with no action as not done. `fabric` acted on 536 of 600 jobs a seed against 570 for `vector_replace`, and every one of its actions used the true value. The gate refused 0 time(s) across all seeds, so the gap in actions is retrieval, not safety: on those jobs no memory about that equipment was in the top 10 for a job-phrased query, where the baseline's top 10 more often held a note restating a value, current or not. The trained retriever (R3) is the lever for that, not the gate.

Harm per 1,000 actions, by seed:

| seed | oracle | vector_append | vector_replace | fabric | fabric_no_lineage |
|---|---|---|---|---|---|
| 6 | 0.0 | 60.7 | 56.7 | 0.0 | 0.0 |
| 7 | 0.0 | 136.9 | 134.0 | 0.0 | 0.0 |
| 8 | 0.0 | 81.2 | 59.5 | 0.0 | 0.0 |
| 9 | 0.0 | 99.5 | 90.9 | 0.0 | 0.0 |
| 10 | 0.0 | 63.4 | 61.3 | 0.0 | 0.0 |
