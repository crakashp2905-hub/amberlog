# O1 — typed claims catch free-text contradictions without a model

Registered in [o1-typed-claims.md](../prereg/o1-typed-claims.md) with the held-out templates fixed
before the extractor existed. Produced by `python -m experiments.o1_typed_claims` at commit `539ba81`;
raw numbers in [o1-typed-claims.json](o1-typed-claims.json). Seeds (1, 2, 3, 4, 5); 32 new claims a seed, each
written to a fresh store holding 24 established facts. No model call anywhere.

Share of each kind of new claim **held for review** (contradictions should be; nothing else should be):

**Held-out world (the thresholds):**

| arm | contradiction | paraphrase | new detail | other subject |
|---|---|---|---|---|
| `structural` | 0.00 | 0.00 | 0.00 | 0.00 |
| `typed` | 1.00 | 0.00 | 0.00 | 0.00 |
| `oracle` | 1.00 | 0.00 | 0.00 | 0.00 |

| O1a recall ≥ structural + 50% of headroom (0.50) | O1b false holds ≤ 0.10 | O1c both, ≥ 4 of 5 seeds |
|---|---|---|---|
| pass (1.00) | pass (0.000) | pass (5/5) |

**C3's world (reported, not a threshold: the author had seen these templates):**

| arm | contradiction | paraphrase | new detail | other subject |
|---|---|---|---|---|
| `structural` | 0.00 | 0.00 | 0.00 | 0.00 |
| `typed` | 0.78 | 0.00 | 0.00 | 0.00 |
| `oracle` | 1.00 | 0.00 | 0.00 | 0.00 |

For comparison, C3 measured model checkers on its own world: Haiku and Sonnet each held 1.00 of
contradictions with 0.067 and 0.058 false holds, at a model call per checked write.
