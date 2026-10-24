# E1 — the cost of recording every exposure

Produced by `python -m experiments.e1_exposure_cost` at commit `aafc559`; raw numbers
in [e1-exposure-cost.json](e1-exposure-cost.json). Machine: Linux x86_64, 4 CPUs, Python 3.13.16. SQLite, 300
retrievals (`k = 5`) per size, profiled with cProfile (which adds overhead in
proportion; the shares are what matter). An operational measurement, not
pre-registered.

| memories | ms per retrieve | exposure events per retrieve | recording ms (share) | ranking share |
|---|---|---|---|---|
| 2,000 | 27.7 | 21 | 3.5 (13%) | 72% |
| 10,000 | 137.9 | 21 | 3.6 (3%) | 84% |

**Reading.** Recording is a minority of a retrieval's cost, and ranking is the
majority. A retrieval writes one event per ranked candidate (pool `4k`), shown
or withheld, so recording costs a fixed few milliseconds while ranking grows
with the store.

**Batching, tried and not kept.** Inserting the hash-chain rows with one
`executemany` instead of one statement each halved the SQL calls a retrieval
makes (48 → 27) and did not move the recording time (1.23 s against 1.22 s per
300 retrievals at 2,000 memories). The cost is SQLite's work per row, not the
calls. Writing the exposures as a single batched event would cut rows, but it
needs a schema change for a cost that is a minority of the total, and it would
coarsen the per-candidate audit trail that credit estimation reads. Not done.

**Where the capacity goes instead.** Read-heavy load is served by one
`agent-api` process per store, which keeps throughput flat as agents are added
(OPERATIONS §4a). Ranking, not recording, is what to optimise next.
