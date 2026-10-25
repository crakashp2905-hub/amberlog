# E1 — the cost of recording every exposure

Produced by `python -m experiments.e1_exposure_cost` at commit `a502d4e`; raw numbers
in [e1-exposure-cost.json](e1-exposure-cost.json). Machine: Linux x86_64, 4 CPUs, Python 3.13.16. SQLite, 300
retrievals (`k = 5`) per size, profiled with cProfile (which adds overhead in
proportion; the shares are what matter). An operational measurement, not
pre-registered.

| memories | ms per retrieve | exposure events per retrieve | recording ms (share) | ranking share |
|---|---|---|---|---|
| 2,000 | 1.2 | 2 | 0.8 (70%) | 13% |
| 10,000 | 1.1 | 2 | 0.5 (53%) | 32% |
| 100,000 | 3.8 | 2 | 0.8 (22%) | 73% |

**Reading.** Recording costs a fixed few milliseconds a retrieval: one event per
ranked candidate (pool `4k`), shown or withheld, whatever the store's size.
Ranking used to grow linearly with the store (138 ms at 10,000 memories at
commit `aafc559`); since lexical search prunes to the rarest query terms, its
share is 73% at 100,000 memories,
and recording is 22%. Fewer events are recorded
too (21 a retrieval at `aafc559`): these queries name one pump, and in a store
this large the words every memory shares ("pump", "relief", "pressure") no
longer bring in near-zero-score candidates, so the pool is the memories that
actually match.

**Batching, tried and not kept.** Inserting the hash-chain rows with one
`executemany` instead of one statement each halved the SQL calls a retrieval
makes (48 → 27) and did not move the recording time (1.23 s against 1.22 s per
300 retrievals at 2,000 memories). The cost is SQLite's work per row, not the
calls. Writing the exposures as a single batched event would cut rows, but it
needs a schema change for a cost that is a minority of the total, and it would
coarsen the per-candidate audit trail that credit estimation reads. Not done.

**Where the capacity goes instead.** Read-heavy load is served by one
`agent-api` process per store, which keeps throughput flat as agents are added
(OPERATIONS §4a).
